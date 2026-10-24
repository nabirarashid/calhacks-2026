import type { Constraint, DesignResult, Goal } from '@shared/contracts';
import type { ApprovalRecord, CommitParamDiff, CommitPreview, CommitResult } from '@/lib/api';

export interface ParameterChange {
  name: string;
  before: string;
  after: string;
}

export interface ConstraintReview {
  label: string;
  ref: string;
  op: Constraint['op'];
  actual: number | null;
  limit: number;
  margin: number | null;
  passed: boolean | null;
  hard: boolean;
}

const display = (value: unknown) => typeof value === 'number' ? String(Number(value.toFixed(4))) : String(value ?? '—');

export const displayCommitValue = (value: unknown): string => {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return display(value);
  if (typeof value === 'string' || typeof value === 'boolean') return String(value);
  try { return JSON.stringify(value); } catch { return String(value); }
};

export function isExactApproval(record: ApprovalRecord | null | undefined, champion: DesignResult): boolean {
  return record?.status === 'approved'
    && record.design_id === champion.design_id
    && record.param_hash === champion.param_hash;
}

export function previewParameterChanges(preview: CommitPreview): CommitParamDiff[] {
  if (Array.isArray(preview.param_diff)) {
    return preview.param_diff.flatMap((raw) => {
      const row = raw as CommitParamDiff & Record<string, unknown>;
      if (!row || typeof row.name !== 'string') return [];
      return [{
        name: row.name,
        before: (row.before ?? row.from ?? row.current) as CommitParamDiff['before'],
        after: (row.after ?? row.to ?? row.planned) as CommitParamDiff['after'],
      }];
    });
  }
  if (!preview.param_diff || typeof preview.param_diff !== 'object') return [];
  return Object.entries(preview.param_diff).map(([name, raw]) => {
    if (Array.isArray(raw)) return { name, before: raw[0] as CommitParamDiff['before'], after: raw[1] as CommitParamDiff['after'] };
    if (raw && typeof raw === 'object') {
      const row = raw as Record<string, unknown>;
      return {
        name,
        before: (row.before ?? row.from ?? row.current) as CommitParamDiff['before'],
        after: (row.after ?? row.to ?? row.planned) as CommitParamDiff['after'],
      };
    }
    return { name, after: raw as CommitParamDiff['after'] };
  });
}

export function previewTarget(preview: CommitPreview): string {
  if (typeof preview.target === 'string') return preview.target;
  const target = preview.target ?? {};
  for (const key of ['label', 'document_name', 'document', 'name', 'workspace_name']) {
    if (typeof target[key] === 'string' && target[key]) return target[key] as string;
  }
  return 'Redacted Onshape target';
}

export interface ReviewedCommitResult {
  success: boolean;
  partial: boolean;
  geometry: NonNullable<CommitResult['geometry']> | NonNullable<CommitResult['geometry_ref']> | CommitResult;
  writtenValues?: Record<string, unknown>;
  readBack?: Record<string, unknown>;
  geometryPassed: boolean;
  geometryDetail: string;
  versionName?: string;
  recoverySteps: string[];
  issues: string[];
}

const DEFAULT_RECOVERY = [
  'Stop editing the target workspace and inspect its current configuration.',
  'Compare the written values with the read-back values shown here.',
  'Restore the last verified Onshape version or manually reset the changed values.',
  'Run a fresh preview and approve the exact champion again before retrying.',
];

export function reviewCommitResult(result: CommitResult): ReviewedCommitResult {
  const geometry = result.geometry ?? result.geometry_ref ?? result;
  const writtenValues = result.written_values ?? result.written ?? result.applied_values;
  const readBack = result.read_back ?? result.readback ?? result.verified_values;
  const geometryCheck = result.geometry_check ?? result.verification?.geometry;
  const versionName = result.version_name ?? result.version?.name;
  const partial = result.partial_write === true
    || result.status === 'partial'
    || (typeof result.error === 'string' && result.error.includes('onshape_partial_write'));
  const issues: string[] = [];
  if (geometry.status !== 'ready') issues.push(`Geometry status is ${geometry.status ?? 'missing'}, not ready.`);
  if (writtenValues === undefined) issues.push('The backend did not return written values.');
  if (readBack === undefined) issues.push('The backend did not return configuration read-back values.');
  if (geometryCheck?.passed !== true) issues.push('The geometry verification did not explicitly pass.');
  if (!versionName) issues.push('The backend did not return a created version name.');
  if (partial) issues.push('The workspace was partially written; recovery is required.');
  if (result.error) issues.push(`Backend reported: ${result.error}`);
  return {
    success: issues.length === 0,
    partial,
    geometry,
    writtenValues,
    readBack,
    geometryPassed: geometryCheck?.passed === true,
    geometryDetail: geometryCheck?.detail ?? geometryCheck?.status ?? 'No geometry-check detail returned.',
    versionName,
    recoverySteps: result.recovery_steps?.length ? result.recovery_steps : partial ? DEFAULT_RECOVERY : [],
    issues,
  };
}

export function parameterChanges(seed: DesignResult | null | undefined, champion: DesignResult): ParameterChange[] {
  const keys = [...new Set([...Object.keys(seed?.params ?? {}), ...Object.keys(champion.params)])].sort();
  return keys.flatMap((name) => {
    const before = seed?.params[name];
    const after = champion.params[name];
    if (Object.is(before, after)) return [];
    return [{ name, before: display(before), after: display(after) }];
  });
}

function actualFor(constraint: Constraint, design: DesignResult): number | null {
  if (constraint.ref.startsWith('param:')) {
    const value = design.params[constraint.ref.slice('param:'.length)];
    return typeof value === 'number' ? value : null;
  }
  const value = design.score.metrics[constraint.ref];
  return typeof value === 'number' ? value : null;
}

export function constraintReview(goal: Goal, design: DesignResult): ConstraintReview[] {
  return goal.constraints.map((constraint) => {
    const actual = actualFor(constraint, design);
    let margin: number | null = null;
    let passed: boolean | null = null;
    if (actual !== null) {
      if (constraint.op === '<=') { margin = constraint.value - actual; passed = actual <= constraint.value; }
      else if (constraint.op === '>=') { margin = actual - constraint.value; passed = actual >= constraint.value; }
      else { const difference = Math.abs(actual - constraint.value); margin = difference === 0 ? 0 : -difference; passed = actual === constraint.value; }
    }
    return { label: constraint.label, ref: constraint.ref, op: constraint.op, actual, limit: constraint.value, margin, passed, hard: constraint.hard };
  });
}

/** Return the champion's evaluated ancestry, condensed to the first failure and subsequent corrections. */
export function correctionSequence(designs: DesignResult[], champion: DesignResult): DesignResult[] {
  const byId = new Map(designs.map((design) => [design.design_id, design]));
  const ancestry = [champion];
  const seen = new Set([champion.design_id]);
  let current = champion;
  while (current.parent_ids.length) {
    const parent = current.parent_ids.map((id) => byId.get(id)).find((design) => design && !seen.has(design.design_id));
    if (!parent) break;
    ancestry.push(parent);
    seen.add(parent.design_id);
    current = parent;
  }
  ancestry.reverse();
  if (ancestry.length < 2) {
    const failed = designs.filter((design) => !design.score.feasible && design.design_id !== champion.design_id)
      .sort((a, b) => a.score.aggregate - b.score.aggregate)[0];
    return failed ? [failed, champion] : [champion];
  }
  const firstFailure = ancestry.findIndex((design) => !design.score.feasible);
  const relevant = firstFailure >= 0 ? ancestry.slice(firstFailure) : ancestry;
  return relevant.length > 4 ? [relevant[0], ...relevant.slice(-3)] : relevant;
}

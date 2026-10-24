import type { Constraint, DesignResult, Goal } from '@shared/contracts';

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

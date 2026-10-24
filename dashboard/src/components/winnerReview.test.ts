import type { DesignResult, Goal } from '@shared/contracts';
import { describe, expect, it } from 'vitest';
import type { CommitPreview, CommitResult } from '@/lib/api';
import {
  constraintReview,
  correctionSequence,
  isExactApproval,
  parameterChanges,
  previewParameterChanges,
  reviewCommitResult,
} from './winnerReview';

const design = (overrides: Partial<DesignResult> = {}): DesignResult => ({
  design_id: 'd1', run_id: 'r1', generation: 0, origin: 'seed', params: { chord: 10, edge: 'round' },
  param_hash: 'hash', parent_ids: [], operator: 'seed', rationale: '',
  score: { metrics: { mass: 12, stability: 2 }, objective_scores: {}, violations: [], feasible: true, aggregate: 1, warnings: [], fidelity: 'fast', eval_ms: 1 },
  timings_ms: {}, ...overrides,
});

const goal: Goal = {
  source_text: 'test', objectives: [], constraints: [
    { ref: 'mass', op: '<=', value: 10, hard: true, label: 'mass cap' },
    { ref: 'stability', op: '>=', value: 1, hard: true, label: 'stability floor' },
    { ref: 'param:chord', op: '==', value: 10, hard: false, label: 'fixed chord' },
    { ref: 'missing', op: '<=', value: 0, hard: false, label: 'missing metric' },
  ], fixed_params: {}, context_overrides: {}, assumptions: [], parsed_by: 'manual',
};

describe('winner review derivations', () => {
  it('lists every parameter changed between seed and champion', () => {
    expect(parameterChanges(design(), design({ params: { chord: 12, edge: 'round', fins: 3 } }))).toEqual([
      { name: 'chord', before: '10', after: '12' },
      { name: 'fins', before: '—', after: '3' },
    ]);
  });

  it('calculates each constraint actual, signed margin, and pass state', () => {
    expect(constraintReview(goal, design()).map(({ actual, margin, passed }) => [actual, margin, passed])).toEqual([
      [12, -2, false], [2, 1, true], [10, 0, true], [null, null, null],
    ]);
  });

  it('follows evaluated parent lineage to show a failure followed by correction', () => {
    const failed = design({ design_id: 'failed', score: { ...design().score, feasible: false, aggregate: -1 } });
    const corrected = design({ design_id: 'corrected', generation: 1, parent_ids: ['failed'] });
    expect(correctionSequence([failed, corrected], corrected)).toEqual([failed, corrected]);
  });

  it('only accepts an approval bound to the exact champion and parameter hash', () => {
    const champion = design();
    expect(isExactApproval({ status: 'approved', design_id: 'd1', param_hash: 'hash' }, champion)).toBe(true);
    expect(isExactApproval({ status: 'approved', design_id: 'd1', param_hash: 'stale' }, champion)).toBe(false);
    expect(isExactApproval({ status: 'approved', design_id: 'other', param_hash: 'hash' }, champion)).toBe(false);
    expect(isExactApproval({ status: 'pending', design_id: 'd1', param_hash: 'hash' }, champion)).toBe(false);
  });

  it('normalizes map-shaped commit preview parameter diffs', () => {
    const preview: CommitPreview = {
      target: 'Demo copy', maturity: 4, expected_calls: 4, checks_planned: ['read back'],
      param_diff: { chord: { before: 10, after: 12 }, fins: [3, 4] },
    };
    expect(previewParameterChanges(preview)).toEqual([
      { name: 'chord', before: 10, after: 12 },
      { name: 'fins', before: 3, after: 4 },
    ]);
  });

  it('requires written values, read-back, an explicit geometry pass, ready geometry, and a version name', () => {
    const complete: CommitResult = {
      geometry: { geometry_key: 'g1', status: 'ready', source: 'onshape_config', onshape_calls: 4, elapsed_ms: 100 },
      written_values: { chord: 12 },
      read_back: { chord: 12 },
      geometry_check: { passed: true, detail: 'volume and bounds match' },
      version_name: 'Darwin verified g1',
    };
    expect(reviewCommitResult(complete).success).toBe(true);

    const legacyGeometryOnly: CommitResult = {
      geometry_key: 'g1', status: 'ready', source: 'onshape_config',
    };
    const legacyReview = reviewCommitResult(legacyGeometryOnly);
    expect(legacyReview.success).toBe(false);
    expect(legacyReview.issues).toEqual(expect.arrayContaining([
      'The backend did not return written values.',
      'The backend did not return configuration read-back values.',
      'The geometry verification did not explicitly pass.',
      'The backend did not return a created version name.',
    ]));

    const failedGeometry = reviewCommitResult({ ...complete, geometry: { ...complete.geometry!, status: 'failed' } });
    expect(failedGeometry.success).toBe(false);
    expect(failedGeometry.issues[0]).toContain('not ready');
  });

  it('marks a partial write as unsuccessful and supplies recovery steps when absent', () => {
    const result = reviewCommitResult({
      status: 'partial',
      geometry: { geometry_key: 'g1', status: 'failed', source: 'onshape_config', onshape_calls: 3, elapsed_ms: 100 },
      written_values: { chord: 12 }, read_back: { chord: 11 },
      geometry_check: { passed: false },
    });
    expect(result.success).toBe(false);
    expect(result.partial).toBe(true);
    expect(result.recoverySteps.length).toBeGreaterThan(0);
  });
});

import type { DesignResult, Goal } from '@shared/contracts';
import { describe, expect, it } from 'vitest';
import { constraintReview, correctionSequence, parameterChanges } from './winnerReview';

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
});

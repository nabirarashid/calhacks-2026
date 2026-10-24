// @vitest-environment node

import { readFileSync } from 'node:fs';

import type { AnyDarwinEvent, ErrorPayload } from '@shared/contracts';
import { beforeEach, describe, expect, it } from 'vitest';

import { emptyRunState, foldEvents, foldRunEvents, reduceEvent } from './reducer';
import { parseJsonl } from './sources';
import {
  selectActiveRun,
  selectCurrentChampion,
  selectSelectedDesign,
  useDashboardStore,
} from './store';

const fixture = readFileSync(
  new URL('../../../shared/fixtures/sample_run.jsonl', import.meta.url),
  'utf8',
);
const events = parseJsonl(fixture);
const completeEvent = events.find(
  (event): event is Extract<AnyDarwinEvent, { type: 'run_complete' }> => event.type === 'run_complete',
);
const startedEvent = events.find(
  (event): event is Extract<AnyDarwinEvent, { type: 'run_started' }> => event.type === 'run_started',
);

describe('event fold', () => {
  it('folds sample_run into exactly the recorded final summary', () => {
    expect(completeEvent).toBeDefined();
    const state = foldRunEvents(events);
    if (!completeEvent) throw new Error('fixture is missing run_complete');
    const expected = completeEvent.payload.summary;

    expect(state.summary).toEqual(expected);
    expect(state.status).toBe('complete');
    expect(state.champion).toEqual(expected.champion);
    expect(state.seedDesign).toEqual(expected.seed_design);
    expect(state.budget).toEqual(expected.budget);
    expect(state.paretoIds).toEqual(expected.pareto_ids);
    expect(state.designs).toHaveLength(64);
    expect(state.generations).toHaveLength(8);
    expect(state.agentMessages).toHaveLength(28);
    expect(state.baselineCurves.cmaes).toEqual(expected.curves.cmaes);
    expect(state.baselineCurves.random).toEqual(expected.curves.random);
    expect(state.landscape?.n).toBe(500);
  });

  it('dedupes by sequence and folds out-of-order events in sequence order', () => {
    const input = [...events].reverse().flatMap((event) => [event, event]);
    const state = foldRunEvents(input);

    expect(state.eventCount).toBe(events.length);
    expect(state.events.map((event) => event.seq)).toEqual(events.map((event) => event.seq));
    expect(state.summary).toEqual(completeEvent?.payload.summary);
  });

  it('keeps independent sequence spaces for different runs', () => {
    if (!startedEvent) throw new Error('fixture is missing run_started');
    const first = startedEvent;
    const second = {
      ...first,
      run_id: 'another_run',
      payload: {
        ...first.payload,
        summary: { ...first.payload.summary, run_id: 'another_run' },
      },
    } as AnyDarwinEvent;
    const folded = foldEvents([first, second, first]);

    expect(folded.runOrder).toEqual([first.run_id, 'another_run']);
    expect(folded.runs[first.run_id].eventCount).toBe(1);
    expect(folded.runs.another_run.eventCount).toBe(1);
  });

  it('reduces error events into system-visible error state', () => {
    const payload: ErrorPayload = {
      component: 'llm',
      code: 'unavailable',
      message: 'using fallback',
      recoverable: true,
      degraded_to: 'fallback_proposer',
    };
    const event: AnyDarwinEvent = {
      v: 1,
      type: 'error',
      run_id: 'run_errors',
      seq: 1,
      ts: 1,
      payload,
    };

    expect(reduceEvent(emptyRunState('run_errors'), event).errors).toEqual([payload]);
  });

  it('tracks the latest progress for each structural analysis stage', () => {
    const state = emptyRunState('run_analysis');
    const progress = (seq: number, pct: number) => ({
      v: 1 as const,
      type: 'analysis_progress' as const,
      run_id: 'run_analysis',
      seq,
      ts: seq,
      payload: { design_id: 'd1', adapter_id: 'structural_fea_v1', stage: 'solve' as const, pct, elapsed_ms: seq * 10 },
    });
    const next = reduceEvent(reduceEvent(state, progress(1, 20)), progress(2, 80));
    expect(next.analysisProgress).toEqual([progress(2, 80).payload]);
  });
});

describe('zustand event store', () => {
  beforeEach(() => useDashboardStore.getState().reset());

  it('dedupes reconnect backlogs and follows the current champion by default', () => {
    useDashboardStore.getState().ingestMany([...events].reverse());
    useDashboardStore.getState().ingestMany(events);

    const state = useDashboardStore.getState();
    const run = selectActiveRun(state);
    expect(run?.eventCount).toBe(events.length);
    expect(run?.summary).toEqual(completeEvent?.payload.summary);
    expect(selectCurrentChampion(state)?.design_id).toBe(completeEvent?.payload.summary.champion?.design_id);
    expect(selectSelectedDesign(state)?.design_id).toBe(completeEvent?.payload.summary.champion?.design_id);
  });

  it('preserves a manual design selection while later events arrive', () => {
    useDashboardStore.getState().ingestMany(events.slice(0, 20));
    const seedId = selectActiveRun(useDashboardStore.getState())?.seedDesign?.design_id;
    expect(seedId).toBeTruthy();
    useDashboardStore.getState().selectDesign(seedId ?? null);
    useDashboardStore.getState().ingestMany(events.slice(20));

    expect(useDashboardStore.getState().selectedDesignId).toBe(seedId);
  });
});

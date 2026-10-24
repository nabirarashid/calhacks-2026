import type { AnyDarwinEvent, DesignResult } from '@shared/contracts';
import { create } from 'zustand';

import { foldRunEvents, type RunFoldState } from './reducer';
import type { EventSource, SourceStatus } from './sources';

export interface DashboardStoreState {
  runs: Record<string, RunFoldState>;
  runOrder: string[];
  activeRunId: string | null;
  selectedDesignId: string | null;
  selectionPinned: boolean;
  sourceStatus: SourceStatus | 'idle';
  sourceError: string | null;
  ingest(event: AnyDarwinEvent): void;
  ingestMany(events: readonly AnyDarwinEvent[]): void;
  setActiveRun(runId: string): void;
  selectDesign(designId: string | null): void;
  setSourceStatus(status: SourceStatus | 'idle'): void;
  setSourceError(error: Error | string | null): void;
  reset(runId?: string): void;
}

function mergeEvents(
  previous: readonly AnyDarwinEvent[],
  incoming: readonly AnyDarwinEvent[],
): AnyDarwinEvent[] {
  const bySeq = new Map(previous.map((event) => [event.seq, event]));
  for (const event of incoming) {
    if (!bySeq.has(event.seq)) bySeq.set(event.seq, event);
  }
  return [...bySeq.values()];
}

export const useDashboardStore = create<DashboardStoreState>((set, get) => ({
  runs: {},
  runOrder: [],
  activeRunId: null,
  selectedDesignId: null,
  selectionPinned: false,
  sourceStatus: 'idle',
  sourceError: null,

  ingest: (event) => get().ingestMany([event]),

  ingestMany: (events) => {
    if (events.length === 0) return;
    set((state) => {
      const runs = { ...state.runs };
      const runOrder = [...state.runOrder];
      const grouped = new Map<string, AnyDarwinEvent[]>();
      for (const event of events) {
        const batch = grouped.get(event.run_id) ?? [];
        batch.push(event);
        grouped.set(event.run_id, batch);
      }

      for (const [runId, incoming] of grouped) {
        if (!runs[runId]) runOrder.push(runId);
        const merged = mergeEvents(runs[runId]?.events ?? [], incoming);
        runs[runId] = foldRunEvents(merged, runId);
      }

      const activeRunId = state.activeRunId ?? events[0].run_id;
      const activeRun = runs[activeRunId];
      const pinnedStillExists = state.selectedDesignId
        ? Boolean(activeRun?.designsById[state.selectedDesignId])
        : false;
      const selectionPinned = state.selectionPinned && pinnedStillExists;
      const selectedDesignId = selectionPinned
        ? state.selectedDesignId
        : activeRun?.championId ?? activeRun?.seedDesign?.design_id ?? null;

      return { runs, runOrder, activeRunId, selectedDesignId, selectionPinned };
    });
  },

  setActiveRun: (runId) => {
    const run = get().runs[runId];
    if (!run) throw new Error(`Unknown run: ${runId}`);
    set({
      activeRunId: runId,
      selectedDesignId: run.championId ?? run.seedDesign?.design_id ?? null,
      selectionPinned: false,
    });
  },

  selectDesign: (designId) => {
    const state = get();
    const run = state.activeRunId ? state.runs[state.activeRunId] : null;
    if (designId !== null && !run?.designsById[designId]) {
      throw new Error(`Unknown design in active run: ${designId}`);
    }
    set({
      selectedDesignId: designId ?? run?.championId ?? run?.seedDesign?.design_id ?? null,
      selectionPinned: designId !== null,
    });
  },

  setSourceStatus: (sourceStatus) => set({ sourceStatus }),
  setSourceError: (error) => set({ sourceError: error ? String(error instanceof Error ? error.message : error) : null }),

  reset: (runId) => {
    if (!runId) {
      set({
        runs: {},
        runOrder: [],
        activeRunId: null,
        selectedDesignId: null,
        selectionPinned: false,
        sourceStatus: 'idle',
        sourceError: null,
      });
      return;
    }

    set((state) => {
      const { [runId]: _removed, ...runs } = state.runs;
      const runOrder = state.runOrder.filter((candidate) => candidate !== runId);
      const activeRunId = state.activeRunId === runId ? runOrder.at(-1) ?? null : state.activeRunId;
      const activeRun = activeRunId ? runs[activeRunId] : null;
      return {
        runs,
        runOrder,
        activeRunId,
        selectedDesignId: activeRun?.championId ?? activeRun?.seedDesign?.design_id ?? null,
        selectionPinned: false,
      };
    });
  },
}));

export const useDarwinStore = useDashboardStore;

export function subscribeSource(source: EventSource): () => void {
  const store = useDashboardStore.getState();
  store.setSourceError(null);
  return source.subscribe({
    next: (event) => useDashboardStore.getState().ingest(event),
    error: (error) => useDashboardStore.getState().setSourceError(error),
    status: (status) => useDashboardStore.getState().setSourceStatus(status),
    complete: () => useDashboardStore.getState().setSourceStatus('complete'),
  });
}

export function selectActiveRun(state: DashboardStoreState): RunFoldState | null {
  return state.activeRunId ? state.runs[state.activeRunId] ?? null : null;
}

export function selectSelectedDesign(state: DashboardStoreState): DesignResult | null {
  const run = selectActiveRun(state);
  return state.selectedDesignId && run ? run.designsById[state.selectedDesignId] ?? null : null;
}

export function selectCurrentChampion(state: DashboardStoreState): DesignResult | null {
  return selectActiveRun(state)?.champion ?? null;
}

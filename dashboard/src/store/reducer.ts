import type {
  AgentMessage,
  AnyDarwinEvent,
  BaselineProgressPayload,
  BudgetStatus,
  CurvePoint,
  DesignResult,
  DesignSpace,
  ErrorPayload,
  Generation,
  GeometryRef,
  LandscapeReadyPayload,
  MetricInfo,
  RunSummary,
} from '@shared/contracts';

export type BaselineMethod = BaselineProgressPayload['method'];

export interface RunFoldState {
  runId: string;
  events: AnyDarwinEvent[];
  eventCount: number;
  lastSeq: number;
  status: RunSummary['status'] | 'pending';
  summary: RunSummary | null;
  designSpace: DesignSpace | null;
  metricCatalog: MetricInfo[];
  designs: DesignResult[];
  designsById: Record<string, DesignResult>;
  generations: Generation[];
  championId: string | null;
  champion: DesignResult | null;
  seedDesign: DesignResult | null;
  geometriesByDesignId: Record<string, GeometryRef>;
  agentMessages: AgentMessage[];
  baselineProgress: Record<BaselineMethod, BaselineProgressPayload[]>;
  baselineCurves: Record<BaselineMethod, CurvePoint[]>;
  baselineBest: Partial<Record<BaselineMethod, DesignResult>>;
  landscape: LandscapeReadyPayload | null;
  budget: BudgetStatus | null;
  paretoIds: string[];
  errors: ErrorPayload[];
}

export interface FoldedDashboardState {
  runs: Record<string, RunFoldState>;
  runOrder: string[];
}

export function emptyRunState(runId: string): RunFoldState {
  return {
    runId,
    events: [],
    eventCount: 0,
    lastSeq: 0,
    status: 'pending',
    summary: null,
    designSpace: null,
    metricCatalog: [],
    designs: [],
    designsById: {},
    generations: [],
    championId: null,
    champion: null,
    seedDesign: null,
    geometriesByDesignId: {},
    agentMessages: [],
    baselineProgress: { cmaes: [], random: [] },
    baselineCurves: { cmaes: [], random: [] },
    baselineBest: {},
    landscape: null,
    budget: null,
    paretoIds: [],
    errors: [],
  };
}

function upsertCurvePoint(curve: CurvePoint[], point: CurvePoint): CurvePoint[] {
  const next = curve.filter((candidate) => candidate.evals !== point.evals);
  next.push(point);
  return next.sort((a, b) => a.evals - b.evals);
}

function replaceGeneration(generations: Generation[], generation: Generation): Generation[] {
  const next = generations.filter((candidate) => candidate.index !== generation.index);
  next.push(generation);
  return next.sort((a, b) => a.index - b.index);
}

function replaceDesign(state: RunFoldState, design: DesignResult): RunFoldState {
  const index = state.designs.findIndex((candidate) => candidate.design_id === design.design_id);
  const designs = [...state.designs];
  if (index === -1) designs.push(design);
  else designs[index] = design;

  const designsById = { ...state.designsById, [design.design_id]: design };
  return {
    ...state,
    designs,
    designsById,
    champion: state.championId === design.design_id ? design : state.champion,
    seedDesign: state.seedDesign?.design_id === design.design_id ? design : state.seedDesign,
  };
}

function patchSummary(
  summary: RunSummary | null,
  patch: Partial<RunSummary>,
): RunSummary | null {
  return summary ? { ...summary, ...patch } : null;
}

/**
 * Apply one already-ordered event. This function is deliberately free of Zustand,
 * timers, sockets, and React so live streams and recordings use the same logic.
 */
export function reduceEvent(state: RunFoldState, event: AnyDarwinEvent): RunFoldState {
  if (state.runId !== event.run_id) {
    throw new Error(`Cannot apply event for ${event.run_id} to run ${state.runId}`);
  }

  let next: RunFoldState = {
    ...state,
    eventCount: state.eventCount + 1,
    lastSeq: event.seq,
  };

  switch (event.type) {
    case 'run_started': {
      const { summary, design_space, metric_catalog } = event.payload;
      return {
        ...next,
        status: summary.status,
        summary,
        designSpace: design_space,
        metricCatalog: metric_catalog,
        championId: summary.champion?.design_id ?? null,
        champion: summary.champion ?? null,
        seedDesign: summary.seed_design ?? null,
        baselineBest: summary.baseline_best,
        budget: summary.budget ?? null,
        paretoIds: summary.pareto_ids,
      };
    }

    case 'design_evaluated': {
      const existingGeometry = next.geometriesByDesignId[event.payload.design.design_id];
      const design = existingGeometry
        ? { ...event.payload.design, geometry: existingGeometry }
        : event.payload.design;
      next = replaceDesign(next, design);
      if (design.origin === 'seed' && next.seedDesign === null) {
        next = {
          ...next,
          seedDesign: design,
          summary: patchSummary(next.summary, { seed_design: design }),
        };
      }
      return next;
    }

    case 'generation_complete': {
      const { generation, pareto_ids } = event.payload;
      const agentCurve = upsertCurvePoint(next.summary?.curves.agent ?? [], {
        evals: generation.evals_used,
        best_aggregate: generation.best_aggregate,
      });
      const curves = { ...(next.summary?.curves ?? {}), agent: agentCurve };
      return {
        ...next,
        generations: replaceGeneration(next.generations, generation),
        paretoIds: pareto_ids,
        summary: patchSummary(next.summary, { curves, pareto_ids }),
      };
    }

    case 'champion_updated': {
      const champion = next.designsById[event.payload.design_id] ?? null;
      return {
        ...next,
        championId: event.payload.design_id,
        champion,
        summary: patchSummary(next.summary, { champion }),
      };
    }

    case 'geometry_ready': {
      const { design_id, geometry } = event.payload;
      next = {
        ...next,
        geometriesByDesignId: { ...next.geometriesByDesignId, [design_id]: geometry },
      };
      const design = next.designsById[design_id];
      if (!design) return next;

      const withGeometry = { ...design, geometry };
      next = replaceDesign(next, withGeometry);
      return {
        ...next,
        summary: patchSummary(next.summary, {
          champion: next.championId === design_id ? withGeometry : next.summary?.champion,
          seed_design: next.seedDesign?.design_id === design_id ? withGeometry : next.summary?.seed_design,
        }),
      };
    }

    case 'agent_message':
      return { ...next, agentMessages: [...next.agentMessages, event.payload.message] };

    case 'baseline_progress': {
      const progress = event.payload;
      const method = progress.method;
      const methodProgress = [...next.baselineProgress[method], progress];
      const methodCurve = upsertCurvePoint(next.baselineCurves[method], progress.curve_point);
      const baselineProgress = { ...next.baselineProgress, [method]: methodProgress };
      const baselineCurves = { ...next.baselineCurves, [method]: methodCurve };
      const baselineBest = { ...next.baselineBest, [method]: progress.best };
      const curves = { ...(next.summary?.curves ?? {}), [method]: methodCurve };
      return {
        ...next,
        baselineProgress,
        baselineCurves,
        baselineBest,
        summary: patchSummary(next.summary, { curves, baseline_best: baselineBest }),
      };
    }

    case 'landscape_ready':
      return { ...next, landscape: event.payload };

    case 'budget_update':
      return {
        ...next,
        budget: event.payload.budget,
        summary: patchSummary(next.summary, { budget: event.payload.budget }),
      };

    case 'run_complete': {
      const summary = event.payload.summary;
      next = {
        ...next,
        status: summary.status,
        summary,
        championId: summary.champion?.design_id ?? next.championId,
        champion: summary.champion ?? next.champion,
        seedDesign: summary.seed_design ?? next.seedDesign,
        baselineBest: summary.baseline_best,
        budget: summary.budget ?? next.budget,
        paretoIds: summary.pareto_ids,
        baselineCurves: {
          cmaes: summary.curves.cmaes ?? next.baselineCurves.cmaes,
          random: summary.curves.random ?? next.baselineCurves.random,
        },
      };
      if (summary.champion) next = replaceDesign(next, summary.champion);
      if (summary.seed_design) next = replaceDesign(next, summary.seed_design);
      return next;
    }

    case 'error':
      return { ...next, errors: [...next.errors, event.payload] };

    default: {
      const exhaustive: never = event;
      return exhaustive;
    }
  }
}

/** Keep the first copy of a sequence number and return canonical wire order. */
export function normalizeRunEvents(events: readonly AnyDarwinEvent[]): AnyDarwinEvent[] {
  const bySeq = new Map<number, AnyDarwinEvent>();
  for (const event of events) {
    if (!bySeq.has(event.seq)) bySeq.set(event.seq, event);
  }
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
}

export function foldRunEvents(
  events: readonly AnyDarwinEvent[],
  runId = events[0]?.run_id,
): RunFoldState {
  if (!runId) throw new Error('foldRunEvents requires a run id or at least one event');
  const matching = events.filter((event) => event.run_id === runId);
  const ordered = normalizeRunEvents(matching);
  const folded = ordered.reduce(reduceEvent, emptyRunState(runId));
  return { ...folded, events: ordered, eventCount: ordered.length };
}

export function foldEvents(events: readonly AnyDarwinEvent[]): FoldedDashboardState {
  const runOrder: string[] = [];
  const grouped = new Map<string, AnyDarwinEvent[]>();
  for (const event of events) {
    if (!grouped.has(event.run_id)) {
      grouped.set(event.run_id, []);
      runOrder.push(event.run_id);
    }
    grouped.get(event.run_id)?.push(event);
  }

  const runs: Record<string, RunFoldState> = {};
  for (const runId of runOrder) runs[runId] = foldRunEvents(grouped.get(runId) ?? [], runId);
  return { runs, runOrder };
}

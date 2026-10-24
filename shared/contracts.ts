// Darwin shared contracts — FROZEN mirror of shared/contracts.py + shared/events.py (contracts-v1).
// Field names are snake_case exactly as on the wire. Python is the source of truth.
export const CONTRACT_VERSION = '1.0.0';

export type ParamValue = number | string;

// ---------------------------------------------------------------- design space
export interface ParamSpec {
  name: string;
  kind: 'continuous' | 'integer' | 'choice';
  unit: string;
  min?: number | null;
  max?: number | null;
  step?: number | null;
  choices?: string[] | null;
  default: ParamValue;
  cad_driven: boolean;
  cad_ref?: string | null;
  description: string;
}

export interface CadSource {
  kind: 'onshape' | 'mock' | 'none';
  doc_url?: string | null;
  mode: 'configuration' | 'custom_feature' | 'feature_post' | 'mock';
  model_revision: string;
}

export interface DesignSpace {
  id: string;
  name: string;
  scorer: string;
  parameters: ParamSpec[];
  context: Record<string, number | string>;
  source: CadSource;
  discovered: boolean;
  notes: string[];
}

export interface DesignParams { values: Record<string, ParamValue>; }

export interface MetricInfo {
  name: string;
  unit: string;
  description: string;
  better: 'higher' | 'lower' | 'target' | 'info';
  typical_min: number;
  typical_max: number;
  default_tolerance?: number | null;
  default_target?: number | null;
}

// ---------------------------------------------------------------- goal
export interface Objective {
  metric: string;
  direction: 'minimize' | 'maximize' | 'target';
  target?: number | null;
  tolerance?: number | null;
  weight: number;
}

export interface Constraint {
  ref: string;                 // metric name or "param:<name>"
  op: '<=' | '>=' | '==';
  value: number;
  hard: boolean;
  label: string;
}

export interface Goal {
  source_text: string;
  objectives: Objective[];
  constraints: Constraint[];
  fixed_params: Record<string, ParamValue>;
  context_overrides: Record<string, number | string>;
  assumptions: string[];
  parsed_by: 'llm' | 'preset' | 'manual' | 'fallback';
}

// ---------------------------------------------------------------- scoring
export interface Violation {
  ref: string;
  op: string;
  limit: number;
  actual: number;
  amount: number;
  hard: boolean;
}

export interface Score {
  metrics: Record<string, number>;
  objective_scores: Record<string, number>;
  violations: Violation[];
  feasible: boolean;
  aggregate: number;
  warnings: string[];
  fidelity: 'fast' | 'high';
  eval_ms: number;
}

// ---------------------------------------------------------------- geometry
export interface GeometryRef {
  geometry_key: string;
  status: 'pending' | 'ready' | 'failed' | 'skipped';
  source: 'onshape_config' | 'onshape_feature' | 'cache' | 'mock' | 'none';
  stl_url?: string | null;
  bbox_mm?: number[] | null;
  volume_mm3?: number | null;
  triangles?: number | null;
  onshape_calls: number;
  regen_status?: string | null;
  error?: string | null;
  elapsed_ms: number;
}

// ---------------------------------------------------------------- designs & runs
export type Origin = 'seed' | 'agent' | 'fallback' | 'baseline_cmaes' | 'baseline_random';
export type Operator = 'seed' | 'novel' | 'mutate' | 'crossover' | 'refine' | 'repair';

export interface Proposal {
  params: Record<string, ParamValue>;
  parent_ids: string[];
  operator: Operator;
  rationale: string;
}

export interface DesignResult {
  design_id: string;
  run_id: string;
  generation: number;
  origin: Origin;
  params: Record<string, ParamValue>;
  param_hash: string;
  parent_ids: string[];
  operator: string;
  rationale: string;
  score: Score;
  pareto_rank?: number | null;
  geometry?: GeometryRef | null;
  timings_ms: Record<string, number>;
}

export interface Directive {
  mode: 'explore' | 'exploit' | 'refine';
  n_explore: number;
  focus_params: string[];
  step_scale: number;
  reason: string;
  source: 'llm' | 'rules';
}

export interface Generation {
  run_id: string;
  index: number;
  design_ids: string[];
  champion_id: string;
  best_aggregate: number;
  mean_aggregate: number;
  feasible_count: number;
  evals_used: number;
  evals_budget: number;
  directive?: Directive | null;
  critic_summary?: string | null;
  elapsed_ms: number;
}

export type AgentRole = 'goal_parser' | 'proposer' | 'critic' | 'strategist' | 'reporter' | 'system';

export interface AgentMessage {
  message_id: string;
  run_id: string;
  generation?: number | null;
  agent: AgentRole;
  kind: 'proposal' | 'insight' | 'warning' | 'directive' | 'report' | 'status';
  model: string;
  summary: string;
  body: string;
  refs: string[];
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
}

// ---------------------------------------------------------------- budgets
export interface OnshapeBudget {
  account_label: string;
  calls_session: number;
  calls_ledger_total: number;
  remaining_estimate: number;
  reserve: number;
  reserve_unlocked: boolean;
  hard_stop: boolean;
  last_synced_at?: string | null;
}

export interface ModelBudget {
  provider: string;
  calls_run: number;
  calls_cap_run: number;
  spend_run_usd: number;
  spend_cap_run_usd: number;
  spend_total_usd: number;
  spend_cap_total_usd: number;
}

export interface BudgetStatus {
  onshape: OnshapeBudget;
  model: ModelBudget;
  evals_used: number;
  evals_budget: number;
}

export interface RunConfig {
  population: number;
  generations: number;
  elites: number;
  eval_budget?: number | null;
  seed: number;
  baselines: Array<'cmaes' | 'random'>;
  early_stop_patience: number;
  min_improvement: number;
  geometry_max_builds: number;
  geometry_min_improvement: number;
  llm_max_calls: number;
  llm_max_spend_usd: number;
  profile: 'demo' | 'full' | 'bench';
}

export interface Preset { label: string; text: string; goal: Goal; }

export interface CurvePoint { evals: number; best_aggregate: number; }

export interface RunSummary {
  run_id: string;
  status: 'running' | 'complete' | 'stopped' | 'failed';
  goal: Goal;
  design_space_id: string;
  config: RunConfig;
  started_at: string;
  finished_at?: string | null;
  champion?: DesignResult | null;
  seed_design?: DesignResult | null;
  baseline_best: Record<string, DesignResult>;
  curves: Record<string, CurvePoint[]>;
  pareto_ids: string[];
  hifi_check?: Score | null;
  budget?: BudgetStatus | null;
  degradations: string[];
  report_url?: string | null;
  recording?: string | null;
}

// ---------------------------------------------------------------- events (shared/events.py)
export type EventType =
  | 'run_started' | 'design_evaluated' | 'generation_complete' | 'champion_updated'
  | 'geometry_ready' | 'agent_message' | 'baseline_progress' | 'landscape_ready'
  | 'budget_update' | 'run_complete' | 'error';

export interface RunStartedPayload { summary: RunSummary; design_space: DesignSpace; metric_catalog: MetricInfo[]; }
export interface DesignEvaluatedPayload { design: DesignResult; }
export interface GenerationCompletePayload { generation: Generation; pareto_ids: string[]; }
export interface ChampionUpdatedPayload { design_id: string; previous_id?: string | null; aggregate: number; delta: number; reason: string; }
export interface GeometryReadyPayload { design_id: string; geometry: GeometryRef; }
export interface AgentMessagePayload { message: AgentMessage; }
export interface BaselineProgressPayload {
  method: 'cmaes' | 'random';
  evals_used: number;
  best_aggregate: number;
  best: DesignResult;
  curve_point: CurvePoint;
}
export interface LandscapeReadyPayload {
  metrics: [string, string];
  points: Array<[number, number, number, boolean]>;   // [x, y, aggregate, feasible]
  n: number;
}
export interface BudgetUpdatePayload { budget: BudgetStatus; }
export interface RunCompletePayload { summary: RunSummary; }
export interface ErrorPayload {
  component: 'llm' | 'onshape' | 'sim' | 'backend';
  code: string;
  message: string;
  recoverable: boolean;
  degraded_to?: string | null;
}

export interface PayloadByType {
  run_started: RunStartedPayload;
  design_evaluated: DesignEvaluatedPayload;
  generation_complete: GenerationCompletePayload;
  champion_updated: ChampionUpdatedPayload;
  geometry_ready: GeometryReadyPayload;
  agent_message: AgentMessagePayload;
  baseline_progress: BaselineProgressPayload;
  landscape_ready: LandscapeReadyPayload;
  budget_update: BudgetUpdatePayload;
  run_complete: RunCompletePayload;
  error: ErrorPayload;
}

export interface DarwinEvent<T extends EventType = EventType> {
  v: 1;
  type: T;
  run_id: string;
  seq: number;
  ts: number;
  payload: PayloadByType[T];
}

/** Discriminated union: switch on `ev.type` to get a typed payload. */
export type AnyDarwinEvent = { [K in EventType]: DarwinEvent<K> }[EventType];

// ---------------------------------------------------------------- REST helpers
export interface HealthResponse {
  ok: boolean;
  contract: string;
  modes: { sim: string; cad: string; llm: string; mode: string };
}
export interface ParseGoalRequest { text: string; design_space_id: string; }
export interface StartRunRequest { goal: Goal; design_space_id: string; config: Partial<RunConfig>; }
export interface StartRunResponse { run_id: string; }
export interface ReplayRequest { recording: string; speed: number; }
export interface DesignRequest { design_id: string; }
export interface DiscoverRequest { doc_url: string; probe: boolean; }

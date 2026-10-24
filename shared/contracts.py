"""Darwin shared contracts — FROZEN at CP0 (tag contracts-v1).

Source of truth for every section. Python 3.9-compatible: no `X | Y`, no `match`.
Changes: additive optional fields only, decided by the contract owner (S3), with a
CONTRACT_VERSION bump. Request changes in your section's CONTRACT_REQUESTS.md.
"""
import hashlib
import json
import math
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.2.0"   # 1.2.0: Goal.editable, investigation events (shared/investigation.py); 1.1.0: AnalysisArtifact

ParamValue = Union[float, int, str]


# ---------------------------------------------------------------- design space

class ParamSpec(BaseModel):
    name: str                                  # snake_case, unique within the space
    kind: Literal["continuous", "integer", "choice"]
    unit: str = ""                             # "mm" | "deg" | "" (dimensionless)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None               # canonical rounding grid (see canonicalize)
    choices: Optional[List[str]] = None
    default: ParamValue
    cad_driven: bool = True                    # False = sim-only, never sent to Onshape
    cad_ref: Optional[str] = None              # configuration input id / variable name
    description: str = ""


class CadSource(BaseModel):
    kind: Literal["onshape", "mock", "none"]
    doc_url: Optional[str] = None              # runtime only; NEVER in committed fixtures
    mode: Literal["configuration", "custom_feature", "feature_post", "mock"] = "configuration"
    model_revision: str = "r1"                 # bump when the Part Studio changes -> new cache keys


class DesignSpace(BaseModel):
    id: str                                    # "fin_v1"
    name: str
    scorer: str                                # sim plugin id
    parameters: List[ParamSpec]
    context: Dict[str, Union[float, str]] = Field(default_factory=dict)  # fixed inputs (reference rocket)
    source: CadSource
    discovered: bool = False
    notes: List[str] = Field(default_factory=list)

    def param(self, name: str) -> ParamSpec:
        for p in self.parameters:
            if p.name == name:
                return p
        raise KeyError(name)


class DesignParams(BaseModel):
    values: Dict[str, ParamValue]


class MetricInfo(BaseModel):                   # published by sim.metric_catalog()
    name: str
    unit: str
    description: str
    better: Literal["higher", "lower", "target", "info"]
    typical_min: float                         # normalization range
    typical_max: float
    default_tolerance: Optional[float] = None  # for "target" objectives
    default_target: Optional[float] = None     # for "target" objectives


# ---------------------------------------------------------------- goal

class Objective(BaseModel):
    metric: str                                # must exist in metric_catalog(space.scorer)
    direction: Literal["minimize", "maximize", "target"]
    target: Optional[float] = None
    tolerance: Optional[float] = None
    weight: float = 1.0


class Constraint(BaseModel):
    ref: str                                   # metric name, or "param:<name>"
    op: Literal["<=", ">=", "=="]
    value: float
    hard: bool = True
    label: str = ""                            # "total fin mass <= 40 g"


class Goal(BaseModel):
    source_text: str
    objectives: List[Objective]
    constraints: List[Constraint] = Field(default_factory=list)
    fixed_params: Dict[str, ParamValue] = Field(default_factory=dict)
    editable: Optional[List[str]] = None       # v1.2: params the user allowed to change; None = all not fixed
    context_overrides: Dict[str, Union[float, str]] = Field(default_factory=dict)
    assumptions: List[str] = Field(default_factory=list)   # shown to the user to confirm
    parsed_by: Literal["llm", "preset", "manual", "fallback"] = "llm"


# ---------------------------------------------------------------- scoring

class Violation(BaseModel):
    ref: str
    op: str
    limit: float
    actual: float
    amount: float                              # |actual-limit| / range; range = typical_max-typical_min
    hard: bool                                 # of the metric, or max-min of the param


class Score(BaseModel):
    metrics: Dict[str, float]
    objective_scores: Dict[str, float]         # each in [0,1], 1 = best
    violations: List[Violation] = Field(default_factory=list)
    feasible: bool                             # no hard violations
    aggregate: float                           # PLAN.md B.6 aggregation rule
    warnings: List[str] = Field(default_factory=list)
    fidelity: Literal["fast", "high"] = "fast"
    eval_ms: float = 0.0


# ---------------------------------------------------------------- geometry

class GeometryRef(BaseModel):
    geometry_key: str
    status: Literal["pending", "ready", "failed", "skipped"]
    source: Literal["onshape_config", "onshape_feature", "cache", "mock", "none"]
    stl_url: Optional[str] = None              # "/api/geometry/{geometry_key}.stl"
    bbox_mm: Optional[List[float]] = None      # [xmin,ymin,zmin,xmax,ymax,zmax], Onshape frame
    volume_mm3: Optional[float] = None
    triangles: Optional[int] = None
    onshape_calls: int = 0                     # calls spent on THIS build (0 if cached)
    regen_status: Optional[str] = None         # "OK" | "WARNING" | "ERROR" | "SANITY_FAIL"
    error: Optional[str] = None
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------- solver evidence (v1.1)

class AnalysisArtifact(BaseModel):              # one solver run on one design (PLAN.md v3 B.3)
    design_id: str
    adapter_id: str                            # "fin_v1" | "structural_analytic_v1" | "structural_fea_v1"
    adapter_version: str
    fidelity: Literal["screening", "verification"]
    metrics: Dict[str, float]
    converged: Optional[bool] = None           # None = no convergence check was run
    mesh: Dict[str, float] = Field(default_factory=dict)        # nodes, elements, h_mm, level
    validity: List[str] = Field(default_factory=list)           # envelope notes / violations
    diagnostics: Dict[str, float] = Field(default_factory=dict)
    solver_version: str = ""
    artifact_paths: List[str] = Field(default_factory=list)     # under .darwin/, never served raw
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------- designs & runs

Origin = Literal["seed", "agent", "fallback", "baseline_cmaes", "baseline_random"]
Operator = Literal["seed", "novel", "mutate", "crossover", "refine", "repair"]


class Proposal(BaseModel):                     # what a proposer returns, before evaluation
    params: Dict[str, ParamValue]
    parent_ids: List[str] = Field(default_factory=list)
    operator: Operator
    rationale: str = ""                        # <= 30 words


class DesignResult(BaseModel):
    design_id: str                             # "{run_id}-g{gen:02d}-{a|f|s|c|r}{idx:02d}"
    run_id: str
    generation: int
    origin: Origin
    params: Dict[str, ParamValue]              # canonicalized
    param_hash: str
    parent_ids: List[str] = Field(default_factory=list)
    operator: str
    rationale: str = ""
    score: Score
    pareto_rank: Optional[int] = None          # 0 = on the front (agent designs only)
    geometry: Optional[GeometryRef] = None
    timings_ms: Dict[str, float] = Field(default_factory=dict)  # propose, eval, geometry
    analysis: Optional[AnalysisArtifact] = None                 # v1.1: verification evidence, if any


ORIGIN_CODE = {"seed": "s", "agent": "a", "fallback": "f", "baseline_cmaes": "c", "baseline_random": "r"}


def make_design_id(run_id: str, generation: int, origin: str, idx: int) -> str:
    return "%s-g%02d-%s%02d" % (run_id, generation, ORIGIN_CODE[origin], idx)


class Directive(BaseModel):                    # strategist output
    mode: Literal["explore", "exploit", "refine"]
    n_explore: int                             # how many of the next N proposals are novel
    focus_params: List[str] = Field(default_factory=list)
    step_scale: float = 0.15                   # mutation radius as a fraction of each range
    reason: str = ""
    source: Literal["llm", "rules"] = "rules"


class Generation(BaseModel):
    run_id: str
    index: int
    design_ids: List[str]
    champion_id: str
    best_aggregate: float
    mean_aggregate: float
    feasible_count: int
    evals_used: int
    evals_budget: int
    directive: Optional[Directive] = None
    critic_summary: Optional[str] = None       # one sentence
    elapsed_ms: float = 0.0


class AgentMessage(BaseModel):
    message_id: str
    run_id: str
    generation: Optional[int] = None
    agent: Literal["goal_parser", "proposer", "critic", "strategist", "reporter", "system"]
    kind: Literal["proposal", "insight", "warning", "directive", "report", "status"]
    model: str                                 # "claude-haiku-5-5" | "rules" | "mock" | "replay"
    summary: str                               # one line for the feed
    body: str = ""                             # short markdown; numbers come from data, not the LLM
    refs: List[str] = Field(default_factory=list)   # design_ids mentioned
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class ModelResult(BaseModel):                  # returned by backend call_model (and the mock provider)
    data: Dict[str, object]                    # validated JSON output
    raw_text: str
    model: str
    provider: str                              # "anthropic" | "mock" | "replay" | ...
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False


# ---------------------------------------------------------------- budgets

class OnshapeBudget(BaseModel):
    account_label: str                         # "prod" | "dev-<name>" | "mock"
    calls_session: int                         # since this process started
    calls_ledger_total: int                    # since ONSHAPE_CALLS_REMAINING_AT
    remaining_estimate: int
    reserve: int
    reserve_unlocked: bool
    hard_stop: bool                            # remaining_estimate <= reserve and not unlocked
    last_synced_at: Optional[str] = None


class ModelBudget(BaseModel):
    provider: str
    calls_run: int
    calls_cap_run: int
    spend_run_usd: float
    spend_cap_run_usd: float
    spend_total_usd: float                     # local ledger; Anthropic Console is ground truth
    spend_cap_total_usd: float


class BudgetStatus(BaseModel):
    onshape: OnshapeBudget
    model: ModelBudget
    evals_used: int
    evals_budget: int


class RunConfig(BaseModel):
    population: int = 8
    generations: int = 8
    elites: int = 3
    eval_budget: Optional[int] = None          # default population*generations; baselines get the same
    seed: int = 7
    baselines: List[Literal["cmaes", "random"]] = Field(default_factory=lambda: ["cmaes", "random"])
    early_stop_patience: int = 3               # generations without >= min_improvement
    min_improvement: float = 0.005
    geometry_max_builds: int = 6               # Onshape builds per run (champions only)
    geometry_min_improvement: float = 0.01
    llm_max_calls: int = 40
    llm_max_spend_usd: float = 0.30
    profile: Literal["demo", "full", "bench"] = "demo"

    def budget(self) -> int:
        return self.eval_budget if self.eval_budget is not None else self.population * self.generations


class Preset(BaseModel):                       # GET /api/presets (demo goal chips)
    label: str
    text: str
    goal: Goal


class CurvePoint(BaseModel):
    evals: int
    best_aggregate: float


class RunSummary(BaseModel):
    run_id: str
    status: Literal["running", "complete", "stopped", "failed"]
    goal: Goal
    design_space_id: str
    config: RunConfig
    started_at: str
    finished_at: Optional[str] = None
    champion: Optional[DesignResult] = None
    seed_design: Optional[DesignResult] = None             # "before" for the winner card
    baseline_best: Dict[str, DesignResult] = Field(default_factory=dict)  # "cmaes", "random"
    curves: Dict[str, List[CurvePoint]] = Field(default_factory=dict)     # "agent", "cmaes", "random"
    pareto_ids: List[str] = Field(default_factory=list)
    hifi_check: Optional[Score] = None                     # champion at fidelity="high"
    budget: Optional[BudgetStatus] = None
    degradations: List[str] = Field(default_factory=list)  # ["llm_fallback@g4", "onshape_cache_only"]
    report_url: Optional[str] = None
    recording: Optional[str] = None


# ---------------------------------------------------------------- shared helpers (frozen)

_DEFAULT_STEP = {"mm": 0.1, "deg": 0.1}


def _decimals(step: float) -> int:
    if step >= 1:
        return 0
    return max(0, int(math.ceil(-math.log10(step) - 1e-9)))


def canonicalize(space: DesignSpace, values: Dict[str, ParamValue]) -> Dict[str, ParamValue]:
    """Fill defaults, clamp to [min,max], round to step, cast integers, validate choices.

    Returns a dict in the space's parameter order. Raises ValueError on an unknown
    param or an invalid choice. Rounding: round(v/step)*step, then clamp. Missing
    `step` defaults to 0.1 for mm/deg and 0.001 otherwise.
    """
    known = {p.name for p in space.parameters}
    unknown = [k for k in values if k not in known]
    if unknown:
        raise ValueError("unknown parameter(s): %s" % ", ".join(sorted(unknown)))
    out = {}  # type: Dict[str, ParamValue]
    for p in space.parameters:
        v = values.get(p.name, p.default)
        if p.kind == "choice":
            v = str(v)
            if not p.choices or v not in p.choices:
                raise ValueError("invalid choice %r for %s (allowed: %s)" % (v, p.name, p.choices))
            out[p.name] = v
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError("non-numeric value %r for %s" % (v, p.name))
        if math.isnan(x) or math.isinf(x):
            raise ValueError("non-finite value for %s" % p.name)
        if p.kind == "integer":
            x = float(int(round(x)))
        else:
            step = p.step or _DEFAULT_STEP.get(p.unit, 0.001)
            x = round(round(x / step) * step, _decimals(step))
        if p.min is not None:
            x = max(x, p.min)
        if p.max is not None:
            x = min(x, p.max)
        out[p.name] = int(x) if p.kind == "integer" else float(x)
    return out


def _sha12(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def param_hash(space: DesignSpace, values: Dict[str, ParamValue]) -> str:
    """sha1(json.dumps(canonicalize(...), sort_keys=True) + space.id)[:12]"""
    canon = canonicalize(space, values)
    return _sha12(json.dumps(canon, sort_keys=True, separators=(",", ":")) + space.id)


def geometry_key(space: DesignSpace, values: Dict[str, ParamValue]) -> str:
    """sha1 over cad_driven params only + space.id + source.model_revision, [:12]"""
    canon = canonicalize(space, values)
    cad = {p.name: canon[p.name] for p in space.parameters if p.cad_driven}
    return _sha12(json.dumps(cad, sort_keys=True, separators=(",", ":"))
                  + space.id + space.source.model_revision)

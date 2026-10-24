"""Darwin websocket / recording events — FROZEN at CP0. See PLAN.md B.8.

Every event on /ws and every line of a run recording (.jsonl) is an `Event`.
Ordering per run: run_started first, run_complete last; within a generation
N x design_evaluated -> champion_updated? -> generation_complete -> budget_update.
agent_message, geometry_ready, baseline_progress may interleave anywhere.
"""
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel

from shared.contracts import (
    AgentMessage, BudgetStatus, CurvePoint, DesignResult, DesignSpace, Generation,
    GeometryRef, MetricInfo, RunSummary,
)
from shared.investigation import DesignApplied, Hypothesis, Notebook, StepResult

EventType = Literal["run_started", "design_evaluated", "generation_complete", "champion_updated",
                    "geometry_ready", "agent_message", "baseline_progress", "landscape_ready",
                    "budget_update", "run_complete", "error", "analysis_progress",
                    "step_planned", "step_result", "notebook_updated", "design_applied"]   # v1.2


class Event(BaseModel):
    v: int = 1
    type: EventType
    run_id: str
    seq: int          # strictly increasing per run; the dashboard dedupes/orders by seq
    ts: float         # unix seconds; replay preserves the gaps (x speed)
    payload: Dict[str, Any]


class RunStarted(BaseModel):
    summary: RunSummary
    design_space: DesignSpace
    metric_catalog: List[MetricInfo]


class DesignEvaluated(BaseModel):
    design: DesignResult


class GenerationComplete(BaseModel):
    generation: Generation
    pareto_ids: List[str]


class ChampionUpdated(BaseModel):
    design_id: str
    previous_id: Optional[str] = None
    aggregate: float
    delta: float
    reason: str = ""


class GeometryReady(BaseModel):
    design_id: str
    geometry: GeometryRef


class AgentMessageEvent(BaseModel):
    message: AgentMessage


class BaselineProgress(BaseModel):
    method: Literal["cmaes", "random"]
    evals_used: int
    best_aggregate: float
    best: DesignResult
    curve_point: CurvePoint


class LandscapeReady(BaseModel):
    metrics: List[str]                 # [x_metric, y_metric]
    points: List[List[Any]]            # [x, y, aggregate, feasible]; <= 2000 points
    n: int


class BudgetUpdate(BaseModel):
    budget: BudgetStatus


class RunComplete(BaseModel):
    summary: RunSummary


class AnalysisProgress(BaseModel):             # v1.1: long solver jobs (FEA) report stages
    design_id: str
    adapter_id: str
    stage: Literal["export", "mesh", "solve", "parse", "converge"]
    pct: float                                 # 0..100 within the whole job
    elapsed_ms: float = 0.0


class ErrorEvent(BaseModel):
    component: Literal["llm", "onshape", "sim", "backend"]
    code: str
    message: str
    recoverable: bool
    degraded_to: Optional[str] = None


PAYLOADS = {
    "run_started": RunStarted,
    "design_evaluated": DesignEvaluated,
    "generation_complete": GenerationComplete,
    "champion_updated": ChampionUpdated,
    "geometry_ready": GeometryReady,
    "agent_message": AgentMessageEvent,
    "baseline_progress": BaselineProgress,
    "landscape_ready": LandscapeReady,
    "budget_update": BudgetUpdate,
    "run_complete": RunComplete,
    "error": ErrorEvent,
    "analysis_progress": AnalysisProgress,
    # v1.2: the hypothesis-driven loop (shared/investigation.py)
    "step_planned": Hypothesis,
    "step_result": StepResult,
    "notebook_updated": Notebook,
    "design_applied": DesignApplied,
}  # type: Dict[str, Type[BaseModel]]


def make_event(type_: str, run_id: str, seq: int, ts: float, payload: BaseModel) -> Event:
    """Build an Event, checking that `payload` is the right model for `type_`."""
    expected = PAYLOADS[type_]
    if not isinstance(payload, expected):
        raise TypeError("payload for %s must be %s, got %s" % (type_, expected.__name__, type(payload).__name__))
    return Event(type=type_, run_id=run_id, seq=seq, ts=ts, payload=payload.model_dump(mode="json"))


def validate_event(ev: Event) -> BaseModel:
    """Validate an Event's payload against its type's model; returns the parsed payload."""
    return PAYLOADS[ev.type].model_validate(ev.payload)

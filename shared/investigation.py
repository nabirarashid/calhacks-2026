"""Darwin contracts v1.2 — the hypothesis-driven loop (PLAN.md Part B.3/B.4). FROZEN at CP-B.

One step = plan (Hypothesis, recorded before any simulation) -> run -> score each Prediction
against the solver (PredictionCheck, computed by code) -> analyze (explanation + lesson,
numeric-claim checked) -> decide (verdict, computed by code) -> learn (Notebook).
Additive to contracts v1/v2. Python 3.9-compatible. Owner: W-C.
"""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from shared.contracts import GeometryRef, ParamValue

Direction = Literal["up", "down", "flat"]
Verdict = Literal["accepted", "rejected", "pivot"]


class Prediction(BaseModel):
    metric: str
    direction: Direction
    pct_low: float                             # expected % change vs the current design
    pct_high: float


class Hypothesis(BaseModel):
    step: int
    levers: List[str]                          # 1-2 editable params
    candidates: List[Dict[str, ParamValue]]    # 1-4 full param dicts to simulate
    principle_ids: List[str] = Field(default_factory=list)   # [] = "exploratory"
    rationale: str                             # <= 40 words, no numbers that aren't in the input
    predictions: List[Prediction]
    source: Literal["llm", "rules"] = "llm"


class PredictionCheck(BaseModel):
    metric: str
    predicted: Prediction
    actual_pct: float
    direction_ok: bool
    in_range: bool
    score: float                               # 1.0 in range, 0.5 direction only, 0.0 wrong


class StepResult(BaseModel):
    step: int
    tested: List[str]                          # design_ids (each also sent as design_evaluated)
    best_id: str
    deltas: Dict[str, float]                   # % change per goal/diagnostic metric vs current
    checks: List[PredictionCheck]
    verdict: Verdict                           # decided by code, never by the LLM
    explanation: str                           # LLM, numeric-claim checked
    lesson: str


class Belief(BaseModel):
    text: str
    evidence_steps: List[int]
    principle_id: Optional[str] = None


class Notebook(BaseModel):
    beliefs: List[Belief] = Field(default_factory=list)
    lever_effects: Dict[str, Dict[str, float]] = Field(default_factory=dict)  # param -> metric -> %/unit
    ruled_out: List[str] = Field(default_factory=list)
    accuracy: List[float] = Field(default_factory=list)   # running mean prediction score per step


class DesignApplied(BaseModel):                 # payload of the design_applied event
    design_id: str
    geometry: GeometryRef
    version: Optional[str] = None              # set for the "before"/"after" versions


def score_prediction(p: Prediction, actual_pct: float, flat_band: float = 2.0) -> PredictionCheck:
    """Deterministic scoring (PLAN.md B.3 step 3). |change| <= flat_band % counts as "flat"."""
    actual_dir = "flat" if abs(actual_pct) <= flat_band else ("up" if actual_pct > 0 else "down")
    lo, hi = min(p.pct_low, p.pct_high), max(p.pct_low, p.pct_high)
    direction_ok = actual_dir == p.direction
    in_range = direction_ok and lo - 1e-9 <= actual_pct <= hi + 1e-9
    return PredictionCheck(metric=p.metric, predicted=p, actual_pct=round(actual_pct, 3),
                           direction_ok=direction_ok, in_range=in_range,
                           score=1.0 if in_range else (0.5 if direction_ok else 0.0))


__all__ = ["Direction", "Verdict", "Prediction", "Hypothesis", "PredictionCheck", "StepResult", "Belief",
           "Notebook", "DesignApplied", "score_prediction"]

"""Proposer: one fast-model call per generation -> N candidate designs with parents and rationale."""
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts import Directive, ModelResult, Proposal

from backend import llm
from backend.agents.base import RunHistory, compact_design, compact_specs, goal_metrics, system_prompt, user_message
from backend.agents.schemas import proposer_schema


def _validate(data: Dict[str, Any]) -> List[Proposal]:
    props = [Proposal.model_validate(p) for p in data.get("proposals", [])]
    if not props:
        raise ValueError("no proposals")
    return props


def build_block(history: RunHistory, n: int, directive: Directive, sens: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    goal = history.goal
    metrics = goal_metrics(goal)
    last = history.last_generation()
    return {
        "n": n,
        "goal": {"text": goal.source_text,
                 "objectives": [o.model_dump(mode="json") for o in goal.objectives],
                 "constraints": [c.model_dump(mode="json") for c in goal.constraints],
                 "fixed_params": goal.fixed_params},
        "params": compact_specs(history.space),
        "top": [compact_design(d, metrics) for d in history.top(8)],
        "last_generation": [compact_design(d, metrics) for d in last if d not in history.top(8)][:8],
        "champion_sensitivity": {p: {m: v for m, v in row.items() if m in metrics} for p, row in sens.items()},
        "critic_insights": history.insights[-5:],
        "directive": directive.model_dump(mode="json"),
        "generation": history.generation, "generations_total": history.generations,
    }


def propose(history: RunHistory, n: int, directive: Directive, sens: Dict[str, Dict[str, float]],
            budget: Optional[llm.RunLLMBudget] = None) -> Tuple[List[Proposal], str, ModelResult]:
    """Raises llm.LLMUnavailable / llm.BudgetExceeded; the run loop falls back to the GA."""
    block = build_block(history, n, directive, sens)
    res = llm.call_model("proposer", system_prompt("proposer", history.space),
                         user_message("Propose %d new designs for generation %d." % (n, history.generation), block),
                         proposer_schema(history.space), max_tokens=3000, effort="low", budget=budget, think=False,
                         validate=_validate)
    return _validate(res.data)[:n], str(res.data.get("hypothesis", "")), res

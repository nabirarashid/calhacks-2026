"""Strategist: explore / exploit / refine, every 3rd generation or on stagnation (rules fallback)."""
from typing import Any, Dict, Optional, Tuple

from shared.contracts import Directive, ModelResult

from backend import llm
from backend.agents.base import RunHistory, compact_design, goal_metrics, system_prompt, user_message
from backend.agents.schemas import strategist_schema


def rules_directive(history: RunHistory, population: int) -> Directive:
    remaining = history.generations - history.generation - 1
    if remaining <= 2:
        return Directive(mode="refine", n_explore=0, step_scale=0.05, source="rules",
                         reason="last %d generation(s): refine around the champion" % max(remaining, 1))
    if history.stagnation >= 2:
        return Directive(mode="explore", n_explore=population // 2, step_scale=0.25, source="rules",
                         reason="no improvement for %d generations" % history.stagnation)
    return Directive(mode="exploit", n_explore=1, step_scale=0.12, source="rules", reason="still improving")


def _clamp(d: Directive, population: int) -> Directive:
    d.n_explore = max(0, min(population, d.n_explore))
    d.step_scale = max(0.01, min(0.5, d.step_scale))
    return d


def strategize(history: RunHistory, population: int, budget: Optional[llm.RunLLMBudget] = None
               ) -> Tuple[Directive, Optional[ModelResult]]:
    metrics = goal_metrics(history.goal)
    block = {
        "generation": history.generation, "generations_total": history.generations, "population": population,
        "best_aggregate_by_generation": [round(x, 4) for x in history.best_by_gen],
        "stagnation": history.stagnation,
        "champion": compact_design(history.champion, metrics) if history.champion else None,
        "top": [compact_design(d, metrics) for d in history.top(5)],
        "previous_directive": history.directive.model_dump(mode="json"),
    }  # type: Dict[str, Any]
    try:
        res = llm.call_model("strategist", system_prompt("strategist"),
                             user_message("Choose the search mode for the next generation.", block),
                             strategist_schema(history.space), max_tokens=1500, effort="low", budget=budget,
                             validate=lambda d: Directive(source="llm", **d))
    except (llm.LLMUnavailable, llm.BudgetExceeded):
        return rules_directive(history, population), None
    return _clamp(Directive(source="llm", **res.data), population), res

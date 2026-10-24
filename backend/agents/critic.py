"""Physicist critic: explains why the champion won and flags suspicious results.

Numbers in its text are checked against its input (numeric-claim check); any
number that is not in the data is replaced with [?] and reported.
"""
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts import DesignResult, MetricInfo, ModelResult

from backend import llm
from backend.agents.base import RunHistory, compact_design, goal_metrics, scrub_claims, system_prompt, user_message
from backend.agents.schemas import critic_schema


def build_block(history: RunHistory, sens: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    metrics = goal_metrics(history.goal)
    champ = history.champion
    seed = history.designs[0] if history.designs else None
    return {
        "goal": {"objectives": [o.model_dump(mode="json") for o in history.goal.objectives],
                 "constraints": [c.label or "%s %s %s" % (c.ref, c.op, c.value) for c in history.goal.constraints]},
        "champion": compact_design(champ, metrics) if champ else None,
        "champion_objective_scores": champ.score.objective_scores if champ else {},
        "seed": compact_design(seed, metrics) if seed else None,
        "runners_up": [compact_design(d, metrics) for d in history.top(4)[1:]],
        "this_generation": [dict(compact_design(d, metrics), warnings=d.score.warnings)
                            for d in history.last_generation()],
        "champion_sensitivity": {p: {m: v for m, v in row.items() if m in metrics} for p, row in sens.items()},
    }


def rules_critique(history: RunHistory, sens: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    """Templated explanation from the largest sensitivity terms (model "rules")."""
    champ = history.champion
    if champ is None:
        return {"why_winner_won": "No feasible champion yet.", "evidence": [], "suspicious": [], "insights": []}
    main = None
    for o in history.goal.objectives:
        for p, row in sens.items():
            mag = abs(row.get(o.metric, 0.0)) * o.weight
            if main is None or mag > main[0]:
                main = (mag, p, o.metric, row.get(o.metric, 0.0))
    if main is None:
        return {"why_winner_won": "%s leads on aggregate score." % champ.design_id, "evidence": [], "suspicious": [],
                "insights": []}
    _, p, m, v = main
    why = "%s leads; %s is the strongest lever on %s (it %s it across its range)." % (
        champ.design_id, p, m, "raises" if v > 0 else "lowers")
    suspicious = [{"design_id": d.design_id, "reason": d.score.warnings[0]}
                  for d in history.last_generation() if d.score.warnings][:2]
    return {"why_winner_won": why, "evidence": [{"param": p, "metric": m, "effect": "raises" if v > 0 else "lowers"}],
            "suspicious": suspicious, "insights": ["Probe %s further around the champion." % p]}


def critique(history: RunHistory, catalog: List[MetricInfo], sens: Dict[str, Dict[str, float]],
             budget: Optional[llm.RunLLMBudget] = None, model: Optional[str] = None
             ) -> Tuple[Dict[str, Any], Optional[ModelResult], List[str]]:
    """Returns (critique, model_result_or_None, scrubbed_numbers). Never raises."""
    block = build_block(history, sens)
    try:
        res = llm.call_model("critic", system_prompt("critic", history.space),
                             user_message("Explain generation %d." % history.generation, block),
                             critic_schema(history.space, catalog), model=model, max_tokens=2000, effort="low",
                             budget=budget, validate=lambda d: d["why_winner_won"])
    except (llm.LLMUnavailable, llm.BudgetExceeded):
        return rules_critique(history, sens), None, []
    data = dict(res.data)
    removed = []  # type: List[str]
    data["why_winner_won"], bad = scrub_claims(str(data.get("why_winner_won", "")), block)
    removed += bad
    insights = []
    for s in data.get("insights", [])[:3]:
        clean, bad = scrub_claims(str(s), block)
        insights.append(clean)
        removed += bad
    data["insights"] = insights
    return data, res, removed


def champion_ids(history: RunHistory) -> List[str]:
    return [history.champion.design_id] if history.champion else []


def suspicious_designs(history: RunHistory, data: Dict[str, Any]) -> List[DesignResult]:
    return [history.by_id[s["design_id"]] for s in data.get("suspicious", []) if s.get("design_id") in history.by_id]

"""Reporter: the critic on the deep model, once per run, for the winner card / engineering report."""
from typing import Any, Dict, Optional, Tuple

from shared.contracts import DesignResult, ModelResult, Score

from backend import llm
from backend.agents.base import RunHistory, compact_design, goal_metrics, scrub_claims, system_prompt, user_message
from backend.agents.schemas import report_schema


def report(history: RunHistory, hifi: Optional[Score], baselines: Dict[str, DesignResult], critic_why: str,
           budget: Optional[llm.RunLLMBudget] = None) -> Tuple[Dict[str, Any], Optional[ModelResult]]:
    metrics = goal_metrics(history.goal)
    champ = history.champion
    block = {
        "goal": history.goal.source_text,
        "objectives": [o.model_dump(mode="json") for o in history.goal.objectives],
        "seed": compact_design(history.designs[0], metrics) if history.designs else None,
        "champion": compact_design(champ, metrics) if champ else None,
        "critic": critic_why,
        "high_fidelity": {"metrics": {m: hifi.metrics.get(m) for m in metrics}, "warnings": hifi.warnings} if hifi else None,
        "baselines_same_budget": {k: compact_design(v, metrics) for k, v in baselines.items()},
        "baseline_note": "baselines are scored on exactly the same number of evaluations as the agent",
        "evaluations": len(history.designs),
    }
    fallback = {"headline": "Champion %s found in %d evaluations." % (champ.design_id if champ else "-", len(history.designs)),
                "narrative": critic_why, "caveats": ["Fast semi-empirical physics; verify before flight."]}
    try:
        res = llm.call_model("reporter", system_prompt("reporter", history.space), user_message("Write the report summary.", block),
                             report_schema(), model=llm.deep_model_or_default(),
                             max_tokens=2500, effort="medium", budget=budget, validate=lambda d: d["narrative"])
    except (llm.LLMUnavailable, llm.BudgetExceeded):
        return fallback, None
    data = dict(res.data)
    for k in ("headline", "narrative"):
        data[k], _ = scrub_claims(str(data.get(k, "")), block)
    data["caveats"] = [scrub_claims(str(c), block)[0] for c in data.get("caveats", [])][:3]
    return data, res

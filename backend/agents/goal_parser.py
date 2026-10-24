"""Goal parser: plain English -> typed Goal over catalog metrics only (1 Haiku call + retries)."""
import re
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts import Constraint, DesignSpace, Goal, MetricInfo, ModelResult, Objective, Preset

from backend import llm
from backend.agents.base import compact_specs, system_prompt, user_message
from backend.agents.schemas import goal_schema


def _cast(space: DesignSpace, name: str, value: str) -> Any:
    p = space.param(name)
    if p.kind == "integer":
        return int(round(float(value)))
    if p.kind == "continuous":
        return float(value)
    if value not in (p.choices or []):
        raise ValueError("invalid choice %r for %s" % (value, name))
    return value


def to_goal(data: Dict[str, Any], text: str, space: DesignSpace, catalog: List[MetricInfo]) -> Goal:
    """Convert the LLM's schema-shaped output into a Goal. Raises on anything unusable."""
    info = {m.name: m for m in catalog}
    objectives = []
    for o in data.get("objectives", []):
        if o["metric"] not in info or info[o["metric"]].better == "info":
            raise ValueError("objective on unknown/info metric %r" % o["metric"])
        target, tol = o.get("target"), o.get("tolerance")
        if o["direction"] == "target":
            target = target if target is not None else info[o["metric"]].default_target
            tol = tol if tol is not None else info[o["metric"]].default_tolerance
            if target is None:
                raise ValueError("target objective on %s needs a target" % o["metric"])
        objectives.append(Objective(metric=o["metric"], direction=o["direction"], target=target, tolerance=tol,
                                    weight=max(0.0, float(o.get("weight", 1.0)))))
    if not objectives:
        raise ValueError("at least one objective is required")
    total = sum(o.weight for o in objectives) or 1.0
    for o in objectives:
        o.weight = round(o.weight / total, 3) if total else round(1.0 / len(objectives), 3)

    params = {p.name for p in space.parameters}
    constraints = []
    for c in data.get("constraints", []):
        ref = c["ref"]
        if not (ref in info or (ref.startswith("param:") and ref[6:] in params)):
            raise ValueError("constraint on unknown ref %r" % ref)
        constraints.append(Constraint(ref=ref, op=c["op"], value=float(c["value"]), hard=bool(c.get("hard", True)),
                                      label=str(c.get("label", ""))))
    fixed = {f["name"]: _cast(space, f["name"], str(f["value"])) for f in data.get("fixed_params", [])}
    overrides = {}  # type: Dict[str, Any]
    if data.get("design_velocity_mps") is not None:
        v = float(data["design_velocity_mps"])
        if not 10.0 <= v <= 400.0:
            raise ValueError("design_velocity_mps %.0f is outside the subsonic model's range (10-400 m/s)" % v)
        overrides["design_velocity_mps"] = v
    return Goal(source_text=text, objectives=objectives, constraints=constraints, fixed_params=fixed,
                context_overrides=overrides, assumptions=[str(a) for a in data.get("assumptions", [])][:6],
                parsed_by="llm")


def fallback_goal(text: str, presets: List[Preset], reason: str) -> Goal:
    """Nearest preset by word overlap, keeping the user's text."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    best = max(presets, key=lambda p: len(words & set(re.findall(r"[a-z]+", p.text.lower()))))
    g = best.goal.model_copy(deep=True)
    g.source_text = text
    g.parsed_by = "fallback"
    g.assumptions = ["Goal parser unavailable (%s); used preset '%s'. Edit before running." % (reason, best.label)]
    m = re.search(r"(\d+(?:\.\d+)?)\s*g(?:rams?)?\b", text.lower())
    for c in g.constraints:
        if m and c.ref == "fin_mass_total_g":
            c.value = float(m.group(1))
            c.label = "total fin mass <= %s g" % m.group(1)
    return g


def parse_goal(text: str, space: DesignSpace, catalog: List[MetricInfo], presets: List[Preset],
               budget: Optional[llm.RunLLMBudget] = None) -> Tuple[Goal, Optional[ModelResult]]:
    block = {"text": text,
             "metrics": [{"name": m.name, "unit": m.unit, "better": m.better, "description": m.description}
                         for m in catalog],
             "params": compact_specs(space),
             "context": {k: v for k, v in space.context.items()
                         if k in ("body_diameter_mm", "design_velocity_mps", "mass_without_fins_g")}}
    try:
        res = llm.call_model("goal_parser", system_prompt("goal_parser"),
                             user_message("Parse this goal.", block), goal_schema(space, catalog),
                             max_tokens=2000, effort="low", budget=budget,
                             validate=lambda d: to_goal(d, text, space, catalog))
    except (llm.LLMUnavailable, llm.BudgetExceeded) as e:
        return fallback_goal(text, presets, str(e)), None
    return to_goal(res.data, text, space, catalog), res

"""Goal parser: plain English -> typed Goal over catalog metrics only (1 Haiku call + retries)."""
import re
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts import Constraint, DesignSpace, Goal, MetricInfo, ModelResult, Objective, Preset

from backend import llm
from backend.agents.base import _packs, compact_specs, system_prompt, unverified_numbers, user_message
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


_ALLOW = re.compile(r"\b(?:(?:you\s+)?(?:can|may|could|are\s+allowed\s+to|feel\s+free\s+to|free\s+to)\s+"
                    r"(?:only\s+)?(?:change|adjust|vary|modify|tweak|edit|play\s+with|move)|only\s+(?:change|adjust|"
                    r"vary|modify|tweak|touch))\b([^.;!?]*)", re.I)
_KEEP = re.compile(r"\b(?:keep|leave|hold|fix|freeze|don'?t\s+(?:change|touch|move)|do\s+not\s+(?:change|touch|move)|"
                   r"without\s+changing|must\s+not\s+change)\b([^.;!?]*)", re.I)


def _aliases(space: DesignSpace) -> List[Tuple[str, List[str]]]:
    """(phrase, params) pairs, longest phrase first. Domain packs supply them; param names are the fallback."""
    names = [p.name for p in space.parameters]
    table = dict(getattr(_packs.get(space.id), "param_aliases", {}) or {})
    for n in names:
        base = re.sub(r"_(deg|mm|frac)$", "", n).replace("_", " ")
        table.setdefault(base, [n])
    pairs = [(phrase.lower(), [p for p in params if p in names]) for phrase, params in table.items()]
    return sorted([pp for pp in pairs if pp[1]], key=lambda pp: -len(pp[0]))


def _params_in(span: str, aliases: List[Tuple[str, List[str]]]) -> List[str]:
    found, text = [], " %s " % span.lower()
    for phrase, params in aliases:
        pattern = r"(?<![a-z])%ss?(?![a-z])" % re.escape(phrase)
        if re.search(pattern, text):
            found += params
            text = re.sub(pattern, " ", text)        # consume, so "flap chord" doesn't also match "chord"
    return list(dict.fromkeys(found))


def infer_editable(text: str, space: DesignSpace) -> Tuple[List[str], List[str]]:
    """Deterministic reading of "you can change X, Y" and "keep Z" -> (allowed, kept)."""
    aliases = _aliases(space)
    allowed = [p for m in _ALLOW.finditer(text) for p in _params_in(m.group(1), aliases)]
    kept = [p for m in _KEEP.finditer(text) for p in _params_in(m.group(1), aliases)]
    return list(dict.fromkeys(allowed)), list(dict.fromkeys(kept))


def resolve_editable(text: str, space: DesignSpace, llm_editable: Optional[List[str]],
                     fixed: Dict[str, Any]) -> Tuple[Optional[List[str]], str]:
    """Which params may Darwin change? Explicit phrases win; the LLM only fills in unusual wording.

    Returns (editable or None for "all not fixed", an assumption sentence for the user to confirm).
    """
    names = [p.name for p in space.parameters]
    allowed, kept = infer_editable(text, space)
    kept = list(dict.fromkeys(kept + list(fixed)))
    if allowed:
        editable = [n for n in names if n in allowed and n not in kept]
    elif llm_editable:
        editable = [n for n in names if n in llm_editable and n not in kept]
    elif kept:
        editable = [n for n in names if n not in kept]
    else:
        return None, "You didn't limit what may change, so Darwin may adjust every parameter."
    if not editable:
        raise ValueError("no parameter is left to change after applying the request's limits")
    held = [n for n in names if n not in editable]
    return editable, "Darwin may change %s; it holds %s fixed." % (
        ", ".join(editable), ", ".join(held) if held else "nothing")


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
    fixed, dropped = {}, []  # type: Dict[str, Any], List[str]
    for f in data.get("fixed_params", []):
        # A pin needs a value the user actually stated ("3 fins"). "Keep the endplates" means hold them
        # at their current value, so an invented value is dropped (Sat 15:40: Haiku pinned 300 mm).
        stated = (not unverified_numbers(str(f["value"]), text)) if re.search(r"\d", str(f["value"])) \
            else str(f["value"]).lower() in text.lower()
        if stated:
            fixed[f["name"]] = _cast(space, f["name"], str(f["value"]))
        else:
            dropped.append(f["name"])
    overrides = {}  # type: Dict[str, Any]
    if data.get("design_velocity_mps") is not None:
        v = float(data["design_velocity_mps"])
        if not 10.0 <= v <= 400.0:
            raise ValueError("design_velocity_mps %.0f is outside the subsonic model's range (10-400 m/s)" % v)
        overrides["design_velocity_mps"] = v
    assumptions = [str(a) for a in data.get("assumptions", [])
                   if not any(name in str(a) for name in dropped)][:6]
    rules = getattr(_packs.get(space.id), "goal_rules", None)
    if rules is not None:      # deterministic domain rules (e.g. rocket_fin's body-tube reading)
        constraints = rules(text, space, constraints, overrides, assumptions)
    llm_editable = [n for n in data.get("editable") or [] if n in params]
    editable, note = resolve_editable(text, space, llm_editable, fixed)
    assumptions = [note] + assumptions[:5]
    return Goal(source_text=text, objectives=objectives, constraints=constraints, fixed_params=fixed,
                editable=editable, context_overrides=overrides, assumptions=assumptions, parsed_by="llm")


def compatible_presets(presets: List[Preset], catalog: List[MetricInfo]) -> List[Preset]:
    """Presets whose every objective and metric constraint exists in this project's catalog."""
    names = {m.name for m in catalog}
    return [p for p in presets if all(o.metric in names for o in p.goal.objectives)
            and all(c.ref in names for c in p.goal.constraints if not c.ref.startswith("param:"))]


def fallback_goal(text: str, presets: List[Preset], reason: str,
                  catalog: Optional[List[MetricInfo]] = None) -> Goal:
    """Nearest compatible preset by word overlap, keeping the user's text."""
    if catalog is not None:
        presets = compatible_presets(presets, catalog)
    if not presets:
        raise llm.LLMUnavailable("goal parser unavailable (%s) and no preset fits this project" % reason)
    words = set(re.findall(r"[a-z]+", text.lower()))
    best = max(presets, key=lambda p: len(words & set(re.findall(r"[a-z]+", p.text.lower()))))
    g = best.goal.model_copy(deep=True)
    g.source_text = text
    g.parsed_by = "fallback"
    g.assumptions = ["Goal parser unavailable (%s); used preset '%s'. Edit before running." % (reason, best.label)]
    m = re.search(r"(\d+(?:\.\d+)?)\s*g(?:rams?)?\b", text.lower())
    grams = {c.name: c for c in catalog or [] if c.unit == "g"}
    for c in g.constraints:
        if m and c.op == "<=" and (c.ref in grams or (catalog is None and c.ref.endswith("_g"))):
            c.value = float(m.group(1))
            label = grams[c.ref].description.lower() if c.ref in grams else c.ref
            c.label = "%s <= %s g" % (label, m.group(1))
    return g


def parse_goal(text: str, space: DesignSpace, catalog: List[MetricInfo], presets: List[Preset],
               budget: Optional[llm.RunLLMBudget] = None) -> Tuple[Goal, Optional[ModelResult]]:
    keys = getattr(_packs.get(space.id), "goal_context_keys", None)     # None = the whole context
    block = {"text": text,
             "metrics": [{"name": m.name, "unit": m.unit, "better": m.better, "description": m.description}
                         for m in catalog],
             "params": compact_specs(space),
             "context": {k: v for k, v in space.context.items()
                         if keys is None or k in keys}}
    try:
        res = llm.call_model("goal_parser", system_prompt("goal_parser", space),
                             user_message("Parse this goal.", block), goal_schema(space, catalog),
                             max_tokens=2000, effort="low", budget=budget, think=False,
                             validate=lambda d: to_goal(d, text, space, catalog))
    except (llm.LLMUnavailable, llm.BudgetExceeded) as e:
        return fallback_goal(text, presets, str(e), catalog), None
    return to_goal(res.data, text, space, catalog), res

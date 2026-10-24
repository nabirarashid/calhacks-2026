"""Fake LLM provider `mock` for backend call_model (PLAN.md B.10). Zero cost, zero network.

Prompt convention (owned by S3, used by every Darwin role): the user message ends
with a fenced ```json block holding that role's structured input. This mock
parses that block and returns schema-shaped JSON:

  goal_parser  in {text, metrics:[MetricInfo], params:[ParamSpec]}         -> Goal-like dict
  proposer     in {n, params:[ParamSpec], top:[{design_id, params, ...}]}  -> {proposals, hypothesis}
  critic       in {champion:{design_id, params, metrics}, sensitivity}      -> critic schema
  strategist   in {generation, stagnation}                                  -> Directive-like dict
  reporter     in {...}                                                     -> {narrative}
  binder       in {discovered:[name], scorer_inputs:[name]}                 -> {mapping}

About 5 % of calls return malformed output (prose around the JSON, or a dropped
field). The choice depends on the prompt text, so a retry with the error appended
usually succeeds. FAKE_LLM_LATENCY scales the latency (default 1.0; 0 in tests).
"""
import hashlib
import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional

from shared.contracts import ModelResult

MODEL = "mock"


def _input_block(user: str) -> Dict[str, Any]:
    blocks = re.findall(r"```json\s*(.*?)```", user, flags=re.DOTALL)
    if not blocks:
        return {}
    try:
        return json.loads(blocks[-1])
    except ValueError:
        return {}


def _rng(*parts: str) -> random.Random:
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def _mutate(spec: Dict[str, Any], value: Any, rng: random.Random, scale: float) -> Any:
    if spec["kind"] == "choice":
        return rng.choice(spec["choices"]) if rng.random() < 0.25 else value
    if spec["kind"] == "integer":
        return int(spec["min"]) + rng.randint(0, int(spec["max"] - spec["min"])) if rng.random() < 0.3 else value
    span = spec["max"] - spec["min"]
    return min(spec["max"], max(spec["min"], float(value) + rng.gauss(0, scale * span)))


def _proposer(inp: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    specs = {p["name"]: p for p in inp.get("params", [])}
    top = inp.get("top", [])
    n = int(inp.get("n", 8))
    scale = float(inp.get("directive", {}).get("step_scale", 0.08))
    props = []
    for i in range(n):
        if top and (i < n - 1 or len(top) < 2):
            parent = top[i % min(len(top), 3)]
            params = {k: _mutate(specs[k], v, rng, scale) for k, v in parent["params"].items() if k in specs}
            props.append({"params": params, "parent_ids": [parent["design_id"]], "operator": "mutate",
                          "rationale": "Perturb %s around a strong parent." % ", ".join(rng.sample(sorted(specs), 2))})
        elif len(top) >= 2:
            a, b = top[0], top[1]
            params = {k: (a["params"][k] if rng.random() < 0.5 else b["params"].get(k, a["params"][k]))
                      for k in a["params"] if k in specs}
            props.append({"params": params, "parent_ids": [a["design_id"], b["design_id"]],
                          "operator": "crossover", "rationale": "Combine the two best designs."})
        else:
            params = {k: (rng.choice(s["choices"]) if s["kind"] == "choice"
                          else rng.randint(int(s["min"]), int(s["max"])) if s["kind"] == "integer"
                          else rng.uniform(s["min"], s["max"])) for k, s in specs.items()}
            props.append({"params": params, "parent_ids": [], "operator": "novel",
                          "rationale": "Explore a fresh region of the space."})
    return {"proposals": props, "hypothesis": "Thinner, swept fins should keep stability while cutting drag and mass."}


def _goal_parser(inp: Dict[str, Any]) -> Dict[str, Any]:
    text = str(inp.get("text", ""))
    low = text.lower()
    objectives = [{"metric": "stability_margin_cal", "direction": "target", "target": 2.0, "tolerance": 0.75,
                   "weight": 0.5}]
    if "drag" in low:
        objectives.append({"metric": "drag_n", "direction": "minimize", "weight": 0.35})
    if any(w in low for w in ("light", "mass", " g", "gram", "weight")):
        objectives.append({"metric": "fin_mass_total_g", "direction": "minimize", "weight": 0.15})
    constraints = [{"ref": "flutter_margin", "op": ">=", "value": 1.5, "hard": True, "label": "flutter-safe (default)"},
                   {"ref": "stability_margin_cal", "op": ">=", "value": 1.0, "hard": True, "label": "stable (default)"}]
    m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", low)
    if m:
        constraints.insert(0, {"ref": "fin_mass_total_g", "op": "<=", "value": float(m.group(1)), "hard": True,
                               "label": "total fin mass <= %s g" % m.group(1)})
    return {"source_text": text, "objectives": objectives, "constraints": constraints, "fixed_params": {},
            "context_overrides": {}, "assumptions": ["mock parser: keyword-based interpretation"], "parsed_by": "llm"}


def _critic(inp: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    champ = inp.get("champion", {})
    sens = inp.get("sensitivity", {})
    param = rng.choice(sorted(sens)) if sens else "sweep_deg"
    return {"why_winner_won": "%s won mainly through %s, which moved stability and drag the right way."
                              % (champ.get("design_id", "The champion"), param),
            "evidence": [{"param": param, "metric": "stability_margin_cal", "effect": "positive"}],
            "suspicious": [], "insights": ["Push %s further while watching flutter margin." % param]}


def _strategist(inp: Dict[str, Any]) -> Dict[str, Any]:
    stagnation = int(inp.get("stagnation", 0))
    mode = "explore" if stagnation >= 2 else "exploit"
    return {"mode": mode, "n_explore": 4 if mode == "explore" else 1, "focus_params": [],
            "step_scale": 0.25 if mode == "explore" else 0.1,
            "reason": "stagnated %d generations" % stagnation if stagnation else "still improving"}


def _investigator_plan(inp: Dict[str, Any]) -> Dict[str, Any]:
    """A plausible, deterministic engineer: try each untried lever once, then the best measured one."""
    nb = inp.get("notebook", {})
    ruled = set(nb.get("ruled_out", []))
    effects = nb.get("lever_effects_pct_per_unit", {})
    objectives = inp.get("goal", {}).get("objectives") or [{"metric": "", "direction": "maximize"}]
    obj, maximize = objectives[0]["metric"], objectives[0].get("direction") != "minimize"
    tried = {lv for s in inp.get("last_steps", []) for lv in s.get("levers", [])} | set(effects)
    open_params = [p for p in inp.get("editable", []) if p["name"] not in ruled]
    if not open_params:
        return {"stop": True, "stop_reason": "every lever is ruled out", "levers": [], "candidates": [],
                "principle_ids": [], "rationale": "", "predictions": []}
    untried = [p for p in open_params if p["name"] not in tried]
    pick = untried[0] if untried else max(open_params, key=lambda p: abs(effects.get(p["name"], {}).get(obj, 0)))
    eff = effects.get(pick["name"], {}).get(obj)
    sign = -1.0 if (eff is not None and (eff < 0) == maximize) else 1.0
    span = float(pick["max"] - pick["min"])
    cands = []
    for frac in (0.08, 0.16):
        v = min(pick["max"], max(pick["min"], float(pick["current"]) + sign * frac * span))
        cands.append({"settings": [{"param": pick["name"], "value": round(v, 3)}]})
    pid = next((p["id"] for p in inp.get("principles", []) if pick["name"] in p.get("levers", "")), None)
    lo, hi = (2.0, 25.0) if maximize else (-25.0, -2.0)
    return {"stop": False, "stop_reason": "", "levers": [pick["name"]], "candidates": cands,
            "principle_ids": [pid] if pid else [],
            "rationale": "Test %s %s, the %s lever, to see how it moves %s." % (
                pick["name"], "up" if sign > 0 else "down", "least explored" if untried else "best measured", obj),
            "predictions": [{"metric": obj, "direction": "up" if maximize else "down", "pct_low": lo, "pct_high": hi}]}


def _investigator_analyze(inp: Dict[str, Any]) -> Dict[str, Any]:
    pct = inp.get("pct_change", {})
    names = [c["metric"] for c in inp.get("predictions", [])] or list(pct)[:2]
    parts = ["%s changed %s%%" % (m, pct[m]) for m in names if m in pct]
    lever = ", ".join(inp.get("hypothesis", {}).get("levers", []))
    return {"explanation": "Changing %s: %s. Verdict %s." % (lever, "; ".join(parts), inp.get("verdict", "")),
            "lesson": "%s %s the goal here." % (lever, "helps" if inp.get("verdict") == "accepted" else "does not help")}


def _respond(role: str, inp: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    if role == "proposer":
        return _proposer(inp, rng)
    if role == "goal_parser":
        return _goal_parser(inp)
    if role == "critic":
        return _critic(inp, rng)
    if role == "strategist":
        return _strategist(inp)
    if role == "investigator_plan":
        return _investigator_plan(inp)
    if role == "investigator_analyze":
        return _investigator_analyze(inp)
    if role == "binder":
        names = inp.get("scorer_inputs", [])
        return {"mapping": {n: n for n in inp.get("discovered", []) if n in names}}
    return {"narrative": "Mock report: the champion balances stability, drag and mass better than the seed."}


def call_model(role: str, system: str, user: str, schema: Optional[dict] = None, *, model: Optional[str] = None,
               max_tokens: int = 2000, effort: str = "low", timeout_s: float = 25.0) -> ModelResult:
    t0 = time.perf_counter()
    rng = _rng(role, system, user)
    data = _respond(role, _input_block(user), rng)
    text = json.dumps(data)
    roll = rng.random()
    if roll < 0.025:
        text = "Sure! Here is my answer:\n" + text + "\nLet me know if you need anything else."
    elif roll < 0.05 and isinstance(data, dict) and data:
        broken = dict(data)
        broken.pop(sorted(broken)[0])
        text = json.dumps(broken)
    time.sleep(float(os.environ.get("FAKE_LLM_LATENCY", "1.0")) * (0.4 + 1.1 * rng.random()))
    tokens_in = len(system + user) // 4
    tokens_out = len(text) // 4 + 200
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = {}
    return ModelResult(data=parsed, raw_text=text, model=model or MODEL, provider="mock", tokens_in=tokens_in,
                       tokens_out=tokens_out, cost_usd=0.0, latency_ms=(time.perf_counter() - t0) * 1000.0)


def roles() -> List[str]:
    return ["goal_parser", "proposer", "critic", "strategist", "reporter", "binder", "investigator_plan",
            "investigator_analyze"]

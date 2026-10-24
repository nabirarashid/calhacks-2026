"""Structured-output JSON schemas for each agent role, built from the DesignSpace.

Claude structured outputs need `additionalProperties: false` on every object and
no numeric bounds, so free-form dicts (params, fixed_params) are expanded into
one property per parameter. Bounds are enforced afterwards by canonicalize().
"""
from typing import Any, Dict, List

from shared.contracts import DesignSpace, MetricInfo

NULLABLE_NUMBER = {"anyOf": [{"type": "number"}, {"type": "null"}]}


def _obj(props: Dict[str, Any], required: List[str] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props),
            "additionalProperties": False}


def _str_list(enum: List[str] = None) -> Dict[str, Any]:
    item = {"type": "string"}  # type: Dict[str, Any]
    if enum:
        item["enum"] = enum
    return {"type": "array", "items": item}


def params_schema(space: DesignSpace) -> Dict[str, Any]:
    props = {}  # type: Dict[str, Any]
    for p in space.parameters:
        if p.kind == "choice":
            props[p.name] = {"type": "string", "enum": list(p.choices or [])}
        elif p.kind == "integer":
            props[p.name] = {"type": "integer"}
        else:
            props[p.name] = {"type": "number"}
    return _obj(props)


def proposer_schema(space: DesignSpace) -> Dict[str, Any]:
    proposal = _obj({
        "params": params_schema(space),
        "parent_ids": _str_list(),
        "operator": {"type": "string", "enum": ["novel", "mutate", "crossover", "refine"]},
        "rationale": {"type": "string"},
    })
    return _obj({"proposals": {"type": "array", "items": proposal}, "hypothesis": {"type": "string"}})


def goal_schema(space: DesignSpace, catalog: List[MetricInfo]) -> Dict[str, Any]:
    metrics = [m.name for m in catalog if m.better != "info"]
    refs = [m.name for m in catalog] + ["param:%s" % p.name for p in space.parameters if p.kind != "choice"]
    objective = _obj({
        "metric": {"type": "string", "enum": metrics},
        "direction": {"type": "string", "enum": ["minimize", "maximize", "target"]},
        "target": NULLABLE_NUMBER, "tolerance": NULLABLE_NUMBER, "weight": {"type": "number"},
    })
    constraint = _obj({
        "ref": {"type": "string", "enum": refs},
        "op": {"type": "string", "enum": ["<=", ">=", "=="]},
        "value": {"type": "number"}, "hard": {"type": "boolean"}, "label": {"type": "string"},
    })
    fixed = _obj({"name": {"type": "string", "enum": [p.name for p in space.parameters]},
                  "value": {"type": "string"}})
    props = {
        "objectives": {"type": "array", "items": objective},
        "constraints": {"type": "array", "items": constraint},
        "fixed_params": {"type": "array", "items": fixed},
        "editable": _str_list([p.name for p in space.parameters]),
        "assumptions": _str_list(),
    }
    if "design_velocity_mps" in space.context:     # only domains that have a design velocity
        props["design_velocity_mps"] = NULLABLE_NUMBER
    return _obj(props)


def critic_schema(space: DesignSpace, catalog: List[MetricInfo]) -> Dict[str, Any]:
    return _obj({
        "why_winner_won": {"type": "string"},
        "evidence": {"type": "array", "items": _obj({
            "param": {"type": "string", "enum": [p.name for p in space.parameters]},
            "metric": {"type": "string", "enum": [m.name for m in catalog]},
            "effect": {"type": "string"}})},
        "suspicious": {"type": "array", "items": _obj({"design_id": {"type": "string"}, "reason": {"type": "string"}})},
        "insights": _str_list(),
    })


def strategist_schema(space: DesignSpace) -> Dict[str, Any]:
    return _obj({
        "mode": {"type": "string", "enum": ["explore", "exploit", "refine"]},
        "n_explore": {"type": "integer"},
        "focus_params": _str_list([p.name for p in space.parameters]),
        "step_scale": {"type": "number"},
        "reason": {"type": "string"},
    })


def report_schema() -> Dict[str, Any]:
    return _obj({"headline": {"type": "string"}, "narrative": {"type": "string"},
                 "caveats": _str_list()})


def investigator_plan_schema(editable: List[str], metrics: List[str], principle_ids: List[str]) -> Dict[str, Any]:
    setting = _obj({"param": {"type": "string", "enum": editable}, "value": {"type": "number"}})
    prediction = _obj({"metric": {"type": "string", "enum": metrics},
                       "direction": {"type": "string", "enum": ["up", "down", "flat"]},
                       "pct_low": {"type": "number"}, "pct_high": {"type": "number"}})
    pids = {"type": "array", "items": {"type": "string", "enum": principle_ids}} if principle_ids \
        else {"type": "array", "items": {"type": "string"}}
    return _obj({
        "stop": {"type": "boolean"},
        "stop_reason": {"type": "string"},
        "levers": _str_list(editable),
        "candidates": {"type": "array", "items": _obj({"settings": {"type": "array", "items": setting}})},
        "principle_ids": pids,
        "rationale": {"type": "string"},
        "predictions": {"type": "array", "items": prediction},
    })


def investigator_analyze_schema() -> Dict[str, Any]:
    return _obj({"explanation": {"type": "string"}, "lesson": {"type": "string"}})


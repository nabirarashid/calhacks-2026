"""Bounded, transport-neutral CAD regeneration probes.

Results intentionally use plain dictionaries until the contracts-v2 module is
available. The callback is supplied by the CAD adapter; this module never
performs network I/O itself.
"""
import hashlib
import json
import math
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

MAX_REGENERATIONS = 9


def generate_cases(parameters: Iterable[Mapping[str, Any]], seed: Mapping[str, Any],
                   *, limit: int = MAX_REGENERATIONS) -> List[Dict[str, Any]]:
    """Return seed, then min/max for each editable numeric parameter, bounded."""
    if isinstance(limit, bool) or limit < 1 or limit > MAX_REGENERATIONS:
        raise ValueError("probe limit must be between 1 and 9")
    cases = [{"case": "seed", "params": dict(seed)}]
    for p in parameters:
        if p.get("role", p.get("editable", True)) in (False, "fixed", "protected"):
            continue
        name = p.get("name", p.get("id"))
        lo, hi = p.get("min"), p.get("max")
        if not name or isinstance(lo, bool) or isinstance(hi, bool):
            continue
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
            continue
        for label, value in (("min", lo), ("max", hi)):
            params = dict(seed)
            params[name] = value
            cases.append({"case": "%s:%s" % (label, name), "params": params})
            if len(cases) >= limit:
                return cases
    return cases


def probe_cache_key(params: Mapping[str, Any], namespace: Optional[str] = None) -> str:
    blob = json.dumps([namespace or "", params], sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _failure_reason(value: Any) -> Optional[str]:
    if not isinstance(value, Mapping):
        return "invalid_result"
    status = str(value.get("status", value.get("regen_status", "ready"))).lower()
    if value.get("error") or status in ("failed", "error", "partial_write", "sanity_fail"):
        return "regeneration_failed"
    if value.get("out_of_range") or status == "out_of_range":
        return "out_of_range"
    if value.get("unit_error") or value.get("scale_error"):
        return "wrong_units_or_scale"
    units = value.get("units")
    if units and str(units).lower() not in ("mm", "millimeter", "millimeters"):
        return "wrong_units_or_scale"
    bbox = value.get("bbox_mm")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 6:
        extents = [abs(float(bbox[i + 3]) - float(bbox[i])) for i in range(3)]
        if any(not math.isfinite(x) or x > 1e6 for x in extents):
            return "wrong_units_or_scale"
        expected = value.get("expected_bbox_mm")
        if isinstance(expected, (list, tuple)) and len(expected) == 6:
            ex = [abs(float(expected[i + 3]) - float(expected[i])) for i in range(3)]
            if any(e > 0 and (a / e > 100 or a / e < 0.01) for a, e in zip(extents, ex)):
                return "wrong_units_or_scale"
    return None


def probe(parameters: Iterable[Mapping[str, Any]], seed: Mapping[str, Any],
          regenerate: Callable[[Mapping[str, Any]], Mapping[str, Any]], *,
          cache: Optional[Dict[str, Mapping[str, Any]]] = None,
          limit: int = MAX_REGENERATIONS,
          cache_namespace: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run generated cases, caching by exact parameter values; fail closed."""
    cache = cache if cache is not None else {}
    rows = []
    for case in generate_cases(parameters, seed, limit=limit):
        params = case["params"]
        key = probe_cache_key(params, cache_namespace)
        cached = key in cache
        try:
            raw = cache[key] if cached else regenerate(params)
            # Budget/authority skips are not geometry evidence and must not
            # poison the persistent cache for the next run.
            raw_status = str(raw.get("status", "ready")).lower() if isinstance(raw, Mapping) else "invalid"
            if not cached and raw_status not in ("skipped", "not_attempted"):
                cache[key] = raw
            reason = _failure_reason(raw)
            status = "failed" if reason else "passed"
            geometry = dict(raw) if isinstance(raw, Mapping) else {}
            if cached:
                geometry["source"] = "cache"
                geometry["onshape_calls"] = 0
        except (Exception,) as exc:
            geometry = {"status": "failed", "error": type(exc).__name__}
            reason, status = "regeneration_failed", "failed"
        rows.append({"case": case["case"], "params": dict(params),
                     "geometry": geometry, "evidence": {"passed": status == "passed",
                     "failure_reason": reason, "cached": cached, "geometry_key": key}})
    return rows

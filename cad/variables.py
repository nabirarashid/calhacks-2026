"""Onshape Variable features: read, write (the live morph), version. PLAN.md B.7 (A3).

Owner W-A; written by W-C with the team's OK (Sat 15:45).

Proven by the morph spike (cad/SPIKE.md): updating a feature regenerates every open tab live
(~0.5 s, 1 call per feature). Configuration updates do not (each viewer keeps its own selected
configuration), so they are never used for the morph. Darwin's parameters are Variable features
(`#aoa_deg`, `#span_mm`, ...) at the top of the Part Studio, named exactly like the ParamSpecs.

Guards on every write: the document must be listed in DARWIN_ONSHAPE_WRITE_DOCS (comma-separated
env var NAMES whose values are document URLs), the ledger must be above its reserve, every target
variable must exist before anything is written, each write is checked for regeneration (a failed
one is reverted), and the values are read back. Functions never raise for Onshape failures: they
return a GeometryRef with a status and an error, like cad.api.build_geometry.
"""
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from shared.contracts import GeometryRef, ParamValue

from cad import cache, stl
from cad.onshape_client import OnshapeError, parse_doc_url

VALUE_PARAM = {"LENGTH": "lengthValue", "ANGLE": "angleValue", "NUMBER": "numberValue", "ANY": "anyValue"}
_LITERAL = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z]*)\s*$")
_UNIT = {"mm": "mm", "millimeter": "mm", "deg": "deg", "degree": "deg", "": ""}


def _api():
    from cad import api
    return api


# ---------------------------------------------------------------- documents

def resolve_doc(doc_url: str, client: Any = None) -> Tuple[str, str, str]:
    """(did, wid, eid). Writes need a workspace (/w/) URL; a URL without /e/ costs 1 lookup call."""
    try:
        return parse_doc_url(doc_url)
    except ValueError:
        parts = [p for p in doc_url.split("?")[0].split("/") if p]
        if "documents" not in parts or "w" not in parts:
            raise
        did, wid = parts[parts.index("documents") + 1], parts[parts.index("w") + 1]
        c = client or _api()._get_client()
        els = c.request("GET", "/documents/d/%s/w/%s/elements" % (did, wid), "inspect",
                        path_template="/documents/d/{did}/w/{wid}/elements",
                        params={"elementType": "PARTSTUDIO"}).json()
        if not els:
            raise ValueError("document has no Part Studio")
        return did, wid, els[0]["id"]


def write_allowed(doc_url: str) -> bool:
    try:
        did = parse_doc_url(doc_url)[0] if "/e/" in doc_url else doc_url.split("/documents/")[1].split("/")[0]
    except (ValueError, IndexError):
        return False
    for name in (os.environ.get("DARWIN_ONSHAPE_WRITE_DOCS") or "").split(","):
        url = os.environ.get(name.strip()) if name.strip() else None
        if url and "/documents/%s/" % did in url:
            return True
    return False


# ---------------------------------------------------------------- reading

def _params_by_id(feature: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p.get("parameterId"): p for p in feature.get("parameters", []) if isinstance(p, dict)}


def parse_literal(expression: str) -> Tuple[Optional[float], str]:
    """'850 mm' -> (850.0, 'mm'); '#a*2' -> (None, ''): not a literal, so never compared or overwritten blindly."""
    m = _LITERAL.match(expression or "")
    if not m:
        return None, ""
    return float(m.group(1)), _UNIT.get(m.group(2).lower(), m.group(2).lower())


def parse_variables(features: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Variable features in a GET /features body -> {name: {feature_id, value_param, expression, value, unit, type}}."""
    out = {}  # type: Dict[str, Dict[str, Any]]
    for f in features.get("features", []):
        if f.get("featureType") != "assignVariable":
            continue
        params = _params_by_id(f)
        name = (params.get("name") or {}).get("value")
        if not name:
            continue
        vtype = str((params.get("variableType") or {}).get("value") or "ANY").upper()
        value_param = VALUE_PARAM.get(vtype, "anyValue")
        if "expression" not in (params.get(value_param) or {}):          # tolerate other layouts
            value_param = next((pid for pid, p in params.items() if "expression" in p and pid != "name"), value_param)
        expression = (params.get(value_param) or {}).get("expression", "")
        value, unit = parse_literal(expression)
        out[name] = {"feature_id": f.get("featureId"), "value_param": value_param, "expression": expression,
                     "value": value, "unit": unit, "type": vtype}
    return out


def format_expression(value: ParamValue, unit: str) -> str:
    """Expression for a ParamSpec unit: 'mm' -> '850 mm', 'deg' -> '8 deg', '' -> '0.3'."""
    text = "%.10g" % float(value)
    unit = _UNIT.get((unit or "").lower(), unit)
    return "%s %s" % (text, unit) if unit else text


def list_variables(doc_url: str) -> Dict[str, Dict[str, Any]]:
    """Live Variable values for the panel's change/keep list. 1 call. Raises OnshapeError on HTTP failure."""
    c = _api()._get_client()
    did, wid, eid = resolve_doc(doc_url, c)
    return parse_variables(c.get_features(did, wid, eid, purpose="inspect"))


# ---------------------------------------------------------------- writing

def _post_feature(c: Any, did: str, wid: str, eid: str, features: Dict[str, Any], feature: Dict[str, Any],
                  source_mv: str) -> Dict[str, Any]:
    body = {"btType": "BTFeatureDefinitionCall-1406", "feature": feature,
            "serializationVersion": features["serializationVersion"], "sourceMicroversion": source_mv,
            "rejectMicroversionSkew": False}
    return c.request("POST", "/partstudios/d/%s/w/%s/e/%s/features/featureid/%s" % (did, wid, eid, feature["featureId"]),
                     "apply", path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features/featureid/{fid}",
                     headers={"Content-Type": "application/json"}, json_body=body).json()


def _with_expression(feature: Dict[str, Any], value_param: str, expression: str) -> Dict[str, Any]:
    f = json.loads(json.dumps(feature))
    for p in f.get("parameters", []):
        if p.get("parameterId") == value_param:
            p["expression"] = expression
    return f


def _fail(key: str, error: str, calls: int, started: float, status: str = "failed",
          regen: str = "ERROR") -> GeometryRef:
    return GeometryRef(geometry_key=key, status=status, source="onshape_feature", error=error[:300],  # type: ignore[arg-type]
                       onshape_calls=calls, regen_status=regen, elapsed_ms=(time.time() - started) * 1000.0)


def apply_values(doc_url: str, params: Mapping[str, ParamValue], units: Mapping[str, str]) -> GeometryRef:
    """Write the changed parameters into their Variable features, so open Onshape tabs morph live.

    `units` maps each param to its ParamSpec unit ("mm", "deg", ""). Only variables whose literal
    value differs are written (1 call each). Then: read back (1 call), export the default STL for the
    3D view and evidence (1-2 calls). Never raises for Onshape failures.
    """
    started = time.time()
    key = hashlib.sha1((doc_url.split("?")[0] + json.dumps(dict(params), sort_keys=True)).encode()).hexdigest()[:12]
    if not write_allowed(doc_url):
        return _fail(key, "write_not_allowed: document is not listed in DARWIN_ONSHAPE_WRITE_DOCS", 0, started,
                     status="skipped", regen="NOT_ATTEMPTED")
    api = _api()
    led = api._get_ledger()
    if led.hard_stop():
        return _fail(key, "onshape_budget_reserve", 0, started, status="skipped", regen="NOT_ATTEMPTED")
    before = led.calls_logged()
    calls = lambda: led.calls_logged() - before  # noqa: E731   (baseline-independent)
    try:
        c = api._get_client()
        did, wid, eid = resolve_doc(doc_url, c)
        features = c.get_features(did, wid, eid, purpose="apply")
        variables = parse_variables(features)
        missing = sorted(n for n in params if n not in variables)
        if missing:
            return _fail(key, "no Variable feature named %s in the Part Studio" % ", ".join(missing), calls(), started,
                         regen="NOT_ATTEMPTED")
        by_id = {f.get("featureId"): f for f in features.get("features", [])}
        changes = []  # type: List[Tuple[str, Dict[str, Any], str]]
        for name, value in params.items():
            var = variables[name]
            target = float(value)
            if var["value"] is not None and abs(var["value"] - target) <= 1e-9 * max(1.0, abs(target)):
                continue
            changes.append((name, var, format_expression(value, units.get(name, var["unit"]))))
        source_mv = features["sourceMicroversion"]
        for name, var, expression in changes:
            feature = by_id[var["feature_id"]]
            resp = _post_feature(c, did, wid, eid, features, _with_expression(feature, var["value_param"], expression),
                                 source_mv)
            source_mv = resp.get("sourceMicroversion") or source_mv
            status = ((resp.get("featureState") or {}).get("featureStatus") or "OK").upper()
            if status != "OK":
                revert = _post_feature(c, did, wid, eid, features, feature, source_mv)
                return _fail(key, "regeneration %s after %s = %s; reverted (%s)" % (
                    status, name, expression, ((revert.get("featureState") or {}).get("featureStatus") or "?")),
                    calls(), started)
        if changes:
            after = parse_variables(c.get_features(did, wid, eid, purpose="apply_verify"))
            wrong = [n for n, _, e in changes if after.get(n, {}).get("expression") != e]
            if wrong:
                return _fail(key, "read-back mismatch for %s" % ", ".join(wrong), calls(), started)
        text = c.export_stl(did, wid, eid, purpose="apply_verify")
        m = stl.measure(None, text)
        ref = GeometryRef(geometry_key=key, status="ready", source="onshape_feature", stl_url="/api/geometry/%s.stl" % key,
                          bbox_mm=m["bbox_mm"], volume_mm3=m["volume_mm3"], triangles=m["triangles"],
                          onshape_calls=calls(), regen_status="OK", elapsed_ms=(time.time() - started) * 1000.0)
        cache.store(ref, text)
        return ref
    except (OnshapeError, ValueError, KeyError) as e:
        return _fail(key, "%s: %s" % (type(e).__name__, e), calls(), started)


def create_version(doc_url: str, name: str) -> Optional[str]:
    """Named version of the workspace ("Before Darwin", "Darwin: ..."). 1 call. Returns the version id or None."""
    if not write_allowed(doc_url) or _api()._get_ledger().hard_stop():
        return None
    try:
        c = _api()._get_client()
        did, wid, _ = resolve_doc(doc_url, c)
        return c.create_version(did, wid, name, purpose="version").get("id")
    except (OnshapeError, ValueError) as e:
        import logging
        logging.getLogger("darwin.cad").warning("create_version failed: %s", e)
        return None


__all__ = ["VALUE_PARAM", "resolve_doc", "write_allowed", "parse_literal", "parse_variables", "format_expression",
           "list_variables", "apply_values", "create_version"]

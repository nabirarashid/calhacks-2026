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
import math
import os
import re
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from shared.contracts import GeometryRef, ParamValue

from cad import cache, stl
from cad.onshape_client import OnshapeError, parse_doc_url

RATE_LIMIT_WAITS_S = (1.5, 3.0)   # Onshape's short-term limiter (HTTP 429, Sat 18:43): wait and retry twice
_stl_refused = False              # the STL download 401s on a cross-host redirect; stop paying 2 calls per step


def _retry(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call fn, retrying only on HTTP 429."""
    for wait in RATE_LIMIT_WAITS_S + (None,):
        try:
            return fn(*args, **kwargs)
        except OnshapeError as e:
            if e.status != 429 or wait is None:
                raise
            time.sleep(wait)

VALUE_PARAM = {"LENGTH": "lengthValue", "ANGLE": "angleValue", "NUMBER": "numberValue", "ANY": "anyValue"}
_LITERAL = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z]*)\s*$")
_UNIT = {"mm": "mm", "millimeter": "mm", "deg": "deg", "degree": "deg", "": ""}
_SAFE_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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

def _feature_body(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize flat and wrapped GET /features rows."""
    feature = row.get("feature", row) if isinstance(row, dict) else {}
    return feature.get("message", feature) if isinstance(feature, dict) else {}


def _parameter_body(parameter: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize flat and ``message``-wrapped Onshape parameters."""
    if not isinstance(parameter, dict):
        return {}
    message = parameter.get("message")
    if isinstance(message, dict):
        body = dict(message)
        body.setdefault("parameterId", parameter.get("parameterId"))
        return body
    return parameter


def _params_by_id(feature: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for parameter in feature.get("parameters", []):
        body = _parameter_body(parameter)
        parameter_id = body.get("parameterId")
        if parameter_id:
            out[parameter_id] = body
    return out


def parse_literal(expression: str) -> Tuple[Optional[float], str]:
    """'850 mm' -> (850.0, 'mm'); '#a*2' -> (None, ''): not a literal, so never compared or overwritten blindly."""
    m = _LITERAL.match(expression or "")
    if not m:
        return None, ""
    return float(m.group(1)), _UNIT.get(m.group(2).lower(), m.group(2).lower())


def parse_variables(features: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Variable features in a GET /features body -> {name: {feature_id, value_param, expression, value, unit, type}}."""
    out = {}  # type: Dict[str, Dict[str, Any]]
    for row in features.get("features", []):
        f = _feature_body(row)
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


def build_variable_feature(name: str, value: ParamValue, unit: str) -> Dict[str, Any]:
    """Build the documented POST payload for a new Variable feature.

    GET responses may wrap fields in ``message`` objects, but the Feature API
    expects create-feature parameter fields directly on each parameter.
    """
    if not isinstance(name, str) or not _SAFE_VARIABLE_NAME.fullmatch(name):
        raise ValueError("variable name must start with a letter or underscore and contain only letters, digits, and underscores")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError("variable value must be a finite number")
    typed = {"mm": ("LENGTH", "lengthValue"),
             "deg": ("ANGLE", "angleValue"),
             "": ("NUMBER", "numberValue")}
    if unit not in typed:
        raise ValueError("unit must be mm, deg, or empty")
    variable_type, value_parameter = typed[unit]
    return {
        "btType": "BTFeatureDefinitionCall-1406",
        "feature": {
            "btType": "BTMFeature-134",
            "featureType": "assignVariable",
            "name": "Variable " + name,
            "parameters": [
                {"btType": "BTMParameterString-149", "parameterId": "name", "value": name},
                {"btType": "BTMParameterEnum-145", "parameterId": "variableType",
                 "enumName": "VariableType", "value": variable_type},
                {"btType": "BTMParameterQuantity-147", "parameterId": value_parameter,
                 "isInteger": False, "expression": format_expression(value, unit)},
            ],
        },
    }


def list_variables(doc_url: str) -> Dict[str, Dict[str, Any]]:
    """Live Variable values for the panel's change/keep list. 1 call. Raises OnshapeError on HTTP failure."""
    c = _api()._get_client()
    did, wid, eid = resolve_doc(doc_url, c)
    if adopted_ids(did, eid):
        return _variables_api(c, did, wid, eid, "inspect")
    return parse_variables(_retry(c.get_features, did, wid, eid, purpose="inspect"))


# ---------------------------------------------------------------- adopted variables (no feature-list reads)
# Onshape's GET /features has a small daily quota of its own (Sat 18:43: exhausted, Retry-After ~20 h)
# while feature writes, the Variables API and bounding boxes stay available. So Darwin "adopts" a Part
# Studio once: it inserts its own Variable features right after the user's (same names, so they take
# over) and keeps their feature ids. Every write after that is POST /features/featureid by id, checked
# through the Variables API; the feature list is never read again.

SERIALIZATION_VERSION = "1.2.23"   # accepted by Onshape for feature writes (from a GET /features, Sat 18:30)


def _ids_path(did: str, eid: str) -> str:
    d = os.path.join(os.environ.get("DARWIN_CACHE_DIR", ".darwin"), "feature_ids")
    return os.path.join(d, "%s_%s.json" % (did, eid))


_COMMITTED_IDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "projects", "rear_wing", "onshape_feature_ids.json")


def adopted_ids(did: str, eid: str) -> Dict[str, str]:
    """{param: featureId} of Darwin's own Variable features in this Part Studio, or {} if not adopted.
    Falls back to the committed wing ids (make outputs) when this is the DARWIN_DOC_WING Part Studio,
    so a teammate's laptop needs no copied files."""
    paths = [_ids_path(did, eid)]
    try:
        wing = parse_doc_url(os.environ.get("DARWIN_DOC_WING", ""))
        if (wing[0], wing[2]) == (did, eid):
            paths.append(_COMMITTED_IDS)
    except ValueError:
        pass
    for path in paths:
        try:
            with open(path) as fh:
                return dict(json.load(fh))
        except (OSError, ValueError):
            continue
    return {}


def _variables_api(c: Any, did: str, wid: str, eid: str, purpose: str) -> Dict[str, Dict[str, Any]]:
    """The Part Studio's effective variables (Variables API, its own quota) in parse_variables' shape."""
    rows = _retry(c.request, "GET", "/variables/d/%s/w/%s/e/%s/variables" % (did, wid, eid), purpose,
                  path_template="/variables/d/{did}/w/{wid}/e/{eid}/variables").json()
    out = {}  # type: Dict[str, Dict[str, Any]]
    for table in rows:
        for v in table.get("variables", []):
            value, unit = parse_literal(v.get("expression") or "")
            out[v["name"]] = {"expression": v.get("expression"), "value": value, "unit": unit, "type": v.get("type")}
    return out


def _microversion(c: Any, did: str, wid: str) -> str:
    return _retry(c.request, "GET", "/documents/d/%s/w/%s/currentmicroversion" % (did, wid), "apply",
                  path_template="/documents/d/{did}/w/{wid}/currentmicroversion").json()["microversion"]


def _write_by_id(c: Any, did: str, wid: str, eid: str, fid: str, name: str, value: ParamValue, unit: str,
                 source_mv: str) -> Dict[str, Any]:
    body = build_variable_feature(name, value, unit)
    body["feature"].update(name="Darwin: " + name, featureId=fid)
    body.update(serializationVersion=SERIALIZATION_VERSION, sourceMicroversion=source_mv)
    return _retry(c.request, "POST", "/partstudios/d/%s/w/%s/e/%s/features/featureid/%s" % (did, wid, eid, fid),
                  "apply", path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features/featureid/{fid}",
                  headers={"Content-Type": "application/json"}, json_body=body).json()


def _bbox(c: Any, did: str, wid: str, eid: str) -> Optional[List[float]]:
    try:
        b = c.request("GET", "/partstudios/d/%s/w/%s/e/%s/boundingboxes" % (did, wid, eid), "apply_verify",
                      path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/boundingboxes").json()
        return [round(b[k] * 1000.0, 3) for k in ("lowX", "lowY", "lowZ", "highX", "highY", "highZ")]
    except (OnshapeError, KeyError, ValueError):
        return None


def adopt_variables(doc_url: str, specs: List[Tuple[str, str, ParamValue]], after_index: int) -> Dict[str, str]:
    """One-time setup: insert "Darwin: <name>" Variable features at `after_index` (just after the user's
    Variables, before any geometry), at the variables' current values, and remember their ids.
    specs = [(name, unit, default)]. Raises on refusal or HTTP failure (a setup tool)."""
    if not write_allowed(doc_url):
        raise ValueError("write_not_allowed: document is not listed in DARWIN_ONSHAPE_WRITE_DOCS")
    c = _api()._get_client()
    did, wid, eid = resolve_doc(doc_url, c)
    current = _variables_api(c, did, wid, eid, "setup")
    base = "/partstudios/d/%s/w/%s/e/%s/features" % (did, wid, eid)
    roll = lambda idx: c.request("POST", base + "/rollback", "setup",  # noqa: E731
                                 path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features/rollback",
                                 headers={"Content-Type": "application/json"}, json_body={"rollbackIndex": idx})
    ids = dict(adopted_ids(did, eid))
    roll(after_index)
    try:
        source_mv = _microversion(c, did, wid)
        for name, unit, default in specs:
            if name in ids:
                continue
            value = (current.get(name) or {}).get("value")
            body = build_variable_feature(name, default if value is None else value, unit)
            body["feature"]["name"] = "Darwin: " + name
            body.update(serializationVersion=SERIALIZATION_VERSION, sourceMicroversion=source_mv)
            resp = c.request("POST", base, "setup", path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features",
                             headers={"Content-Type": "application/json"}, json_body=body).json()
            ids[name] = resp["feature"]["featureId"]
            source_mv = resp.get("sourceMicroversion") or source_mv
    finally:
        roll(-1)
        os.makedirs(os.path.dirname(_ids_path(did, eid)), exist_ok=True)
        with open(_ids_path(did, eid), "w") as fh:
            json.dump(ids, fh)
    return ids


def _apply_adopted(c: Any, did: str, wid: str, eid: str, ids: Dict[str, str], params: Mapping[str, ParamValue],
                   units: Mapping[str, str], key: str, started: float, calls: Callable[[], int]) -> GeometryRef:
    missing = sorted(n for n in params if n not in ids)
    if missing:
        return _fail(key, "no Darwin Variable feature for %s (re-run adopt_variables)" % ", ".join(missing), calls(),
                     started, regen="NOT_ATTEMPTED")
    current = _variables_api(c, did, wid, eid, "apply")
    changes = [(n, v) for n, v in params.items()
               if (current.get(n) or {}).get("value") is None
               or abs(current[n]["value"] - float(v)) > 1e-9 * max(1.0, abs(float(v)))]
    source_mv = _microversion(c, did, wid) if changes else ""
    for name, value in changes:
        unit = units.get(name, (current.get(name) or {}).get("unit", ""))
        resp = _write_by_id(c, did, wid, eid, ids[name], name, value, unit, source_mv)
        source_mv = resp.get("sourceMicroversion") or source_mv
        status = ((resp.get("featureState") or {}).get("featureStatus") or "OK").upper()
        if status != "OK":
            old = (current.get(name) or {}).get("value")
            if old is not None:
                _write_by_id(c, did, wid, eid, ids[name], name, old, unit, source_mv)
            return _fail(key, "regeneration %s after %s = %s; reverted" % (status, name, value), calls(), started)
    if changes:
        after = _variables_api(c, did, wid, eid, "apply_verify")
        wrong = [n for n, v in changes
                 if (after.get(n) or {}).get("expression") != format_expression(v, units.get(n, ""))]
        if wrong:
            return _fail(key, "read-back mismatch for %s" % ", ".join(wrong), calls(), started)
    return GeometryRef(geometry_key=key, status="ready", source="onshape_feature", bbox_mm=_bbox(c, did, wid, eid),
                       onshape_calls=calls(), regen_status="OK", elapsed_ms=(time.time() - started) * 1000.0)


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
        body = _parameter_body(p)
        if body.get("parameterId") == value_param:
            if isinstance(p.get("message"), dict):
                p["message"]["expression"] = expression
            else:
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
        ids = adopted_ids(did, eid)
        if ids:
            return _apply_adopted(c, did, wid, eid, ids, params, units, key, started, calls)
        features = _retry(c.get_features, did, wid, eid, purpose="apply")
        variables = parse_variables(features)
        missing = sorted(n for n in params if n not in variables)
        if missing:
            return _fail(key, "no Variable feature named %s in the Part Studio" % ", ".join(missing), calls(), started,
                         regen="NOT_ATTEMPTED")
        by_id = {_feature_body(row).get("featureId"): _feature_body(row)
                 for row in features.get("features", [])}
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
            resp = _retry(_post_feature, c, did, wid, eid, features,
                          _with_expression(feature, var["value_param"], expression), source_mv)
            source_mv = resp.get("sourceMicroversion") or source_mv
            status = ((resp.get("featureState") or {}).get("featureStatus") or "OK").upper()
            if status != "OK":
                revert = _post_feature(c, did, wid, eid, features, feature, source_mv)
                return _fail(key, "regeneration %s after %s = %s; reverted (%s)" % (
                    status, name, expression, ((revert.get("featureState") or {}).get("featureStatus") or "?")),
                    calls(), started)
        if changes:
            after = parse_variables(_retry(c.get_features, did, wid, eid, purpose="apply_verify"))
            wrong = [n for n, _, e in changes if after.get(n, {}).get("expression") != e]
            if wrong:
                return _fail(key, "read-back mismatch for %s" % ", ".join(wrong), calls(), started)
        global _stl_refused
        try:
            if _stl_refused:
                raise OnshapeError("skipped after an earlier 401", 401)
            text = c.export_stl(did, wid, eid, purpose="apply_verify")
        except OnshapeError as e:            # the variables are written and verified; the STL is only evidence
            _stl_refused = _stl_refused or e.status in (401, 403)
            return GeometryRef(geometry_key=key, status="ready", source="onshape_feature",
                               error="stl_export: %s" % str(e)[:200], onshape_calls=calls(), regen_status="OK",
                               elapsed_ms=(time.time() - started) * 1000.0)
        m = stl.measure(None, text)
        ref = GeometryRef(geometry_key=key, status="ready", source="onshape_feature", stl_url="/api/geometry/%s.stl" % key,
                          bbox_mm=m["bbox_mm"], volume_mm3=m["volume_mm3"], triangles=m["triangles"],
                          onshape_calls=calls(), regen_status="OK", elapsed_ms=(time.time() - started) * 1000.0)
        cache.store(ref, text)
        return ref
    except (OnshapeError, ValueError, KeyError) as e:
        return _fail(key, "%s: %s" % (type(e).__name__, e), calls(), started)


def ensure_variables(doc_url: str, specs: List[Tuple[str, str, ParamValue]]) -> List[str]:
    """Create any missing Variable features at the TOP of the Part Studio: specs = [(name, unit, default)].

    Optional setup shortcut for a new Part Studio (cad/WING_PARTSTUDIO.md step 1 does the same by hand):
    afterwards the geometry only has to reference #name. Moves the rollback bar to 0, inserts the
    features (built by build_variable_feature), restores the bar (cad/SPIKE.md). Returns the names created.
    Raises on refusal or HTTP failure: this is a setup tool, not a demo path.
    """
    if not write_allowed(doc_url):
        raise ValueError("write_not_allowed: document is not listed in DARWIN_ONSHAPE_WRITE_DOCS")
    api = _api()
    if api._get_ledger().hard_stop():
        raise ValueError("onshape_budget_reserve")
    c = api._get_client()
    did, wid, eid = resolve_doc(doc_url, c)
    base = "/partstudios/d/%s/w/%s/e/%s/features" % (did, wid, eid)
    existing = parse_variables(c.get_features(did, wid, eid, purpose="setup"))
    missing = [(n, u, d) for n, u, d in specs if n not in existing]
    if not missing:
        return []
    payloads = [build_variable_feature(n, d, u) for n, u, d in missing]     # validates names/values first
    roll = lambda idx: c.request("POST", base + "/rollback", "setup",  # noqa: E731
                                 path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features/rollback",
                                 headers={"Content-Type": "application/json"}, json_body={"rollbackIndex": idx})
    roll(0)
    try:
        f = c.get_features(did, wid, eid, purpose="setup")
        source_mv = f["sourceMicroversion"]
        for body in payloads:
            body = dict(body, serializationVersion=f["serializationVersion"], sourceMicroversion=source_mv)
            resp = c.request("POST", base, "setup", path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features",
                             headers={"Content-Type": "application/json"}, json_body=body).json()
            source_mv = resp.get("sourceMicroversion") or source_mv
    finally:
        roll(-1)
    return [n for n, _, _ in missing]


def create_version(doc_url: str, name: str) -> Optional[str]:
    """Named version of the workspace ("Before Darwin", "Darwin: ..."). 1 call. Returns the version id or None."""
    if not write_allowed(doc_url) or _api()._get_ledger().hard_stop():
        return None
    try:
        c = _api()._get_client()
        did, wid, _ = resolve_doc(doc_url, c)
        return _retry(c.create_version, did, wid, name, purpose="version").get("id")
    except (OnshapeError, ValueError) as e:
        import logging
        logging.getLogger("darwin.cad").warning("create_version failed: %s", e)
        return None


__all__ = ["VALUE_PARAM", "resolve_doc", "write_allowed", "parse_literal", "parse_variables", "format_expression",
           "build_variable_feature", "list_variables", "apply_values", "ensure_variables", "create_version",
           "adopt_variables", "adopted_ids"]

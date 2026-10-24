"""Transport-neutral Onshape inventory parsing and safe local persistence.

The v2 shared contract is not present in this checkout. These helpers return
plain dictionaries matching the documented CadInventory field names; the
backend can adapt them to its eventual frozen model without guessing it here.
"""
import json
import os
import re
from typing import Any, Dict, Mapping


_SECRET_KEYS = re.compile(
    r"(secret|token|authorization|credential|api.?key|access.?key|"
    r"documentid|workspaceid|elementid|microversionid|sourcemicroversion|did|wid|eid)$",
    re.I,
)
_URL_ID = re.compile(r"(?i)(/documents/)[^/?#]+|(/(?:w|v|m)/)[^/?#]+|(/e/)[^/?#]+")


def sanitize_payload(value: Any, key: str = "") -> Any:
    """Copy a payload while removing credentials and document/workspace IDs.

    Parameter and feature identifiers remain in the returned inventory because
    they are required to address editable inputs. Persisted API payloads omit
    document/workspace/element/microversion IDs and redact IDs embedded in URLs.
    """
    if _SECRET_KEYS.search(str(key)):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(k): sanitize_payload(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(v, key) for v in value]
    if isinstance(value, tuple):
        return [sanitize_payload(v, key) for v in value]
    if isinstance(value, str):
        return _URL_ID.sub(lambda m: (m.group(1) or "") + "[redacted]" if m.group(1)
                           else (m.group(2) or "") + "[redacted]" if m.group(2)
                           else (m.group(3) or "") + "[redacted]", value)
    return value


def parse_inventory(payload: Mapping[str, Any], *, onshape_calls: int = 0) -> Dict[str, Any]:
    """Normalize an aggregated API response into the v2 inventory shape."""
    if not isinstance(payload, Mapping):
        raise ValueError("inventory payload must be an object")
    if isinstance(onshape_calls, bool) or not 0 <= int(onshape_calls) <= 6:
        raise ValueError("inspect must use between zero and six Onshape calls")
    elements = payload.get("elements", [])
    config = payload.get("configuration", {})
    features_blob = payload.get("features", {})
    parts_blob = payload.get("parts", [])
    mass_blob = payload.get("mass_properties", payload.get("massProperties", {}))
    if isinstance(features_blob, Mapping):
        features = features_blob.get("features", [])
        microversion = features_blob.get("sourceMicroversion") or config.get("sourceMicroversion", "")
    else:
        features = features_blob
        microversion = config.get("sourceMicroversion", "")
    if not isinstance(config, Mapping):
        config = {}
    if not isinstance(features, list):
        raise ValueError("features must be a list")
    if not isinstance(parts_blob, list):
        parts_blob = parts_blob.get("parts", []) if isinstance(parts_blob, Mapping) else []

    config_inputs = []
    params = config.get("configurationParameters", [])
    current = {r.get("parameterId"): r for r in config.get("currentConfiguration", [])
               if isinstance(r, Mapping)}
    for raw_parameter in params if isinstance(params, list) else []:
        if not isinstance(raw_parameter, Mapping):
            continue
        p = raw_parameter.get("message", raw_parameter)
        if not isinstance(p, Mapping) or not p.get("parameterId"):
            continue
        r = p.get("rangeAndDefault") or {}
        row = current.get(p["parameterId"], {})
        options = p.get("options", p.get("choices", []))
        choices = []
        if isinstance(options, list):
            choices = [o.get("optionName", o.get("name", o.get("option")))
                       if isinstance(o, Mapping) else o for o in options]
            choices = [value for value in choices if value is not None]
        config_inputs.append({
            "id": p["parameterId"], "name": p.get("parameterName", p.get("name", p["parameterId"])),
            "kind": "quantity" if "rangeAndDefault" in p else "choice",
            "unit": r.get("units", row.get("units", "")),
            "min": r.get("minValue"), "max": r.get("maxValue"),
            "default": r.get("defaultValue", p.get("defaultValue", row.get("value"))),
            "choices": choices,
        })

    parsed_features = []
    mate_connectors = []
    for raw_feature in features:
        if not isinstance(raw_feature, Mapping):
            continue
        feature = raw_feature.get("feature", raw_feature)
        if not isinstance(feature, Mapping):
            continue
        f = feature.get("message", feature)
        if not isinstance(f, Mapping):
            continue
        fid = f.get("featureId", f.get("id", ""))
        name = f.get("name", "")
        typ = f.get("featureType", f.get("type", ""))
        parsed_features.append({"id": fid, "name": name, "type": typ,
                                "suppressed": bool(f.get("suppressed", raw_feature.get("suppressed", False)))})
        if "mateconnector" in str(typ).replace("_", "").lower() or "mate connector" in str(typ).lower():
            origin = f.get("origin", f.get("origin_mm"))
            if isinstance(origin, Mapping):
                origin = [origin.get(k, 0.0) for k in ("x", "y", "z")]
            mate_connectors.append({"id": fid, "name": name, "origin_mm": origin})

    mass_by_id = mass_blob.get("bodies", mass_blob) if isinstance(mass_blob, Mapping) else {}
    parsed_parts = []
    for part in parts_blob:
        if not isinstance(part, Mapping):
            continue
        pid = part.get("partId", part.get("part_id", part.get("id", "")))
        props = mass_by_id.get(pid, {}) if isinstance(mass_by_id, Mapping) else {}
        if not props and len(parts_blob) == 1 and isinstance(mass_by_id, Mapping):
            props = mass_by_id.get("-all-", {})
        if isinstance(props, list):
            props = props[0] if props else {}
        if not isinstance(props, Mapping):
            props = {}
        bbox = _bbox_mm(part.get("bbox_mm", part.get("boundingBox")))
        volume = part.get("volume_mm3")
        if volume is None:
            volume = _nominal(props.get("volume_mm3"), 1.0)
        if volume is None:
            volume = _nominal(props.get("volume"), 1e9)  # Onshape mass properties use m^3.
        mass = part.get("mass_g")
        if mass is None:
            mass = _nominal(props.get("mass_g"), 1.0)
        if mass is None:
            mass = _nominal(props.get("mass"), 1e3)  # Onshape mass properties use kg.
        parsed_parts.append({
            "part_id": pid, "name": part.get("name", ""),
            "volume_mm3": volume, "mass_g": mass, "bbox_mm": bbox,
        })
    unit_data = payload.get("units", {})
    units = dict(unit_data) if isinstance(unit_data, Mapping) else {}
    return {"provider": "onshape", "source_microversion": str(microversion or ""),
            "units": units, "parts": parsed_parts, "config_inputs": config_inputs,
            "features": parsed_features, "mate_connectors": mate_connectors,
            "export_formats": list(payload.get("export_formats", ["stl", "step"])),
            "onshape_calls": int(onshape_calls), "elements": sanitize_payload(elements)}


def _nominal(value: Any, scale: float) -> Any:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return float(value) * scale


def _bbox_mm(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    keys = ("minX", "minY", "minZ", "maxX", "maxY", "maxZ")
    if all(key in value for key in keys):
        return [float(value[key]) * 1000.0 for key in keys]
    return value


def save_sanitized_raw(payload: Mapping[str, Any], path: str) -> str:
    """Persist a sanitized response snapshot under a caller-selected path."""
    safe = sanitize_payload(payload)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(safe, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path

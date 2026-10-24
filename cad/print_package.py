"""Offline export of a measured STL and its minimal design label."""
import json
import os
import re
import tempfile
import zipfile
from typing import Dict, Optional

from shared.contracts import DesignSpace, ParamValue, canonicalize, geometry_key

from cad import api, cache


def _safe_name(value: str) -> str:
    """Keep caller controlled identifiers out of paths and archive metadata."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_-.")
    if not cleaned or cleaned in (".", ".."):
        raise ValueError("invalid print package name")
    return cleaned[:80]


def _score_data(score):
    if score is None:
        raise ValueError("score is required for a print label")
    if hasattr(score, "model_dump"):
        score = score.model_dump(mode="json")
    elif hasattr(score, "dict"):
        score = score.dict()
    if not isinstance(score, dict):
        raise ValueError("score must be a score model or mapping")
    allowed = {"metrics", "objective_scores", "violations", "feasible", "aggregate",
               "warnings", "fidelity", "eval_ms"}
    if set(score) - allowed:
        raise ValueError("score contains unsupported fields")
    # A plain JSON round-trip rejects unserializable objects and normalizes
    # model-specific values before placing them in the archive.
    try:
        return json.loads(json.dumps(score, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("score is not finite JSON data") from exc


def export_print_package(space: DesignSpace, params: Dict[str, ParamValue],
                         out_dir, design_id: Optional[str] = None,
                         score=None, verifier=None) -> str:
    """Return a deterministic ZIP containing ``design.stl`` and ``label.json``.

    No identifiers from the CAD provider, URLs, credentials, or raw API payloads
    are included. The optional metadata is mandatory in practice because the
    package label contract requires both a score and design ID.
    """
    if not design_id:
        raise ValueError("design_id is required for a print label")
    safe_id = _safe_name(str(design_id))
    score_json = _score_data(score)
    canon = canonicalize(space, params)
    key = geometry_key(space, canon)

    ref = api.build_geometry(space, canon, verifier=verifier)
    if ref.status != "ready" or ref.geometry_key != key:
        raise RuntimeError("geometry is not ready: %s" % (ref.error or ref.status))
    source = cache.stl_path(key)
    if not source or not os.path.isfile(source):
        raise RuntimeError("ready geometry has no local STL")

    label = {
        "design_id": safe_id,
        "geometry_key": key,
        "params": canon,
        "score": score_json,
        "units": "mm",
    }
    label_bytes = (json.dumps(label, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with open(source, "rb") as stream:
        stl_bytes = stream.read()
    if not stl_bytes:
        raise RuntimeError("local STL is empty")

    os.makedirs(out_dir, exist_ok=True)
    destination = os.path.join(str(out_dir), "darwin_print_%s.zip" % key)
    # Build entirely in memory so failed writes cannot leave a partial package.
    import io
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for filename, payload in (("design.stl", stl_bytes), ("label.json", label_bytes)):
            info = zipfile.ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            bundle.writestr(info, payload)
    fd, temporary = tempfile.mkstemp(prefix=".print-", suffix=".zip", dir=str(out_dir))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(archive.getvalue())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return destination

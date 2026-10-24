"""cad public API (S1). The only module backend/ is allowed to import.

Contract: PLAN.md B.7. build_geometry NEVER raises — every failure comes back as
a GeometryRef with a status and an error string, so the run loop can carry on and
the dashboard can fall back to its parametric preview.
"""
import os
import time
from typing import Dict, Optional

from shared.contracts import (DesignSpace, GeometryRef, ParamValue, canonicalize,
                              geometry_key)
from shared.contracts import OnshapeBudget

from cad import cache, stl
from cad.ledger import BudgetExceeded, Ledger

_ledger = None          # lazily built so importing cad/ never needs env vars
_client = None


def _get_ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger.from_env()
    return _ledger


def _get_client():
    """Build the HTTP client on first use. Raises OnshapeError if keys are unset."""
    global _client
    if _client is None:
        from cad.onshape_client import OnshapeClient
        _client = OnshapeClient(ledger=_get_ledger())
    return _client


def budget_status() -> OnshapeBudget:
    return _get_ledger().budget_status()


def geometry_file(key: str) -> Optional[str]:
    """Local STL path for the backend to serve, or None."""
    return cache.stl_path(key)


def _doc_url(space: DesignSpace) -> Optional[str]:
    # Fixtures strip doc_url, so the runtime value comes from the environment.
    return space.source.doc_url or os.environ.get("DARWIN_FIN_DOC_URL") or None


def _cad_values(space: DesignSpace, canon: Dict[str, ParamValue]) -> Dict[str, object]:
    """Only the cad_driven params, keyed by their Onshape configuration id."""
    out = {}
    for spec in space.parameters:
        if spec.cad_driven and spec.name in canon:
            out[spec.cad_ref or spec.name] = canon[spec.name]
    return out


def _cad_units(space: DesignSpace) -> Dict[str, str]:
    return {(spec.cad_ref or spec.name): spec.unit
            for spec in space.parameters if spec.cad_driven and spec.unit}


def _fail(key: str, error: str, started: float,
          regen: Optional[str] = None, status: str = "failed") -> GeometryRef:
    return GeometryRef(
        geometry_key=key, status=status, source="none", error=error,
        regen_status=regen, onshape_calls=0,
        elapsed_ms=round((time.time() - started) * 1000.0, 2))


def build_geometry(space: DesignSpace, params: Dict[str, ParamValue],
                   allow_network: bool = True) -> GeometryRef:
    """Regenerate `params` in Onshape and return a measured GeometryRef.

    Order: cache, budget, export, sanity check, store. Never raises.
    """
    started = time.time()
    try:
        canon = canonicalize(space, params)
        key = geometry_key(space, canon)
    except Exception as exc:
        return _fail("invalid", "canonicalize failed: %s" % exc, started)

    # 1. Cache — zero calls, zero network.
    hit = cache.load(key)
    if hit is not None:
        hit.elapsed_ms = round((time.time() - started) * 1000.0, 2)
        return hit

    if not allow_network:
        return _fail(key, "cache_miss_offline", started, status="skipped")

    # 2. Budget floor.
    led = _get_ledger()
    if led.hard_stop():
        return _fail(key, "onshape_budget_reserve", started, status="skipped")

    url = _doc_url(space)
    if not url:
        return _fail(key, "DARWIN_FIN_DOC_URL is not set", started)

    mode = space.source.mode
    if mode != "configuration":
        # Verdicts B and C land in configured.py / feature_post.py once the
        # spike picks a path; until then say so plainly instead of guessing.
        return _fail(key, "cad mode '%s' not implemented yet (spike verdict pending)" % mode,
                     started)

    # 3. Configured export.
    before = led.calls_total()
    try:
        from cad.onshape_client import parse_doc_url, encode_configuration
        did, wid, eid = parse_doc_url(url)
        client = _get_client()
        cfg = encode_configuration(_cad_values(space, canon), _cad_units(space))
        text = client.export_stl(did, wid, eid, configuration=cfg, purpose="build")
    except BudgetExceeded as exc:
        return _fail(key, "onshape_budget_reserve: %s" % exc, started, status="skipped")
    except Exception as exc:
        spent = led.calls_total() - before
        ref = _fail(key, "%s: %s" % (type(exc).__name__, exc), started, regen="ERROR")
        ref.onshape_calls = spent
        return ref

    spent = led.calls_total() - before

    # 4. Sanity check against the frozen analytic geometry (zero calls).
    try:
        measured = stl.measure(canon, text)
    except Exception as exc:
        ref = _fail(key, "unparseable STL: %s" % exc, started, regen="ERROR")
        ref.onshape_calls = spent
        return ref

    ok = measured.get("regen_status") == "OK"
    ref = GeometryRef(
        geometry_key=key,
        status="ready" if ok else "failed",
        source="onshape_config",
        stl_url="/api/geometry/%s.stl" % key,
        bbox_mm=measured["bbox_mm"],
        volume_mm3=measured["volume_mm3"],
        triangles=measured["triangles"],
        onshape_calls=spent,
        regen_status=measured.get("regen_status"),
        error=None if ok else "; ".join(measured.get("sanity_reasons", [])),
        elapsed_ms=round((time.time() - started) * 1000.0, 2),
    )

    # 5. Store even a sanity failure, so the raw export can be inspected later.
    try:
        cache.store(ref, text)
    except Exception:
        pass
    return ref


def commit_to_document(space: DesignSpace, params: Dict[str, ParamValue]) -> GeometryRef:
    """Write the champion into the Onshape doc so it is visible in the UI.

    Needs spike step 7 (can POST /elements/.../configuration set defaults in 1
    call?) before it can be implemented cheaply.
    """
    started = time.time()
    canon = canonicalize(space, params)
    return _fail(geometry_key(space, canon),
                 "commit_to_document pending spike step 7", started)


def export_print_package(space: DesignSpace, params: Dict[str, ParamValue],
                         out_dir: str) -> Optional[str]:
    raise NotImplementedError("print package lands with Tier 2")


def discover_design_space(doc_url: str, probe: bool = False) -> DesignSpace:
    raise NotImplementedError("auto-discovery lands with Tier 3")

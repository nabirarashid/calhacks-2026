"""cad public API (S1). The only module backend/ is allowed to import.

Contract: PLAN.md B.7. build_geometry NEVER raises — every failure comes back as
a GeometryRef with a status and an error string, so the run loop can carry on and
the dashboard can fall back to its parametric preview.
"""
import math
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from shared.contracts import (DesignSpace, GeometryRef, ParamValue, canonicalize,
                              geometry_key)
from shared.contracts import OnshapeBudget

from cad import cache, stl
from cad.ledger import BudgetExceeded, Ledger

_ledger = None          # lazily built so importing cad/ never needs env vars
_client = None
_configuration_cache = {}


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
                   allow_network: bool = True, verifier=None) -> GeometryRef:
    """Regenerate `params` in Onshape and return a measured GeometryRef.

    Order: cache, budget, export, sanity check, store. Never raises.
    """
    started = time.time()
    try:
        canon = canonicalize(space, params)
        key = geometry_key(space, canon)
    except Exception as exc:
        return _fail("invalid", "canonicalize failed: %s" % exc, started)

    # Generic CAD cannot decide whether an exported shape is valid for a
    # project. Refuse even a cache hit unless the domain pack supplied its
    # verifier; otherwise an old ready sidecar could silently bypass policy.
    if verifier is None:
        return _fail(key, "domain_geometry_verifier_required", started,
                     regen="SANITY_FAIL")

    # 1. Cache — zero calls, zero network.
    hit = cache.load(key)
    if hit is not None:
        # Cache metadata is not proof that this verifier accepted the STL. The
        # verifier may have changed since the sidecar was written, so re-read
        # and verify the actual geometry for every request.
        path = cache.stl_path(key)
        if not path:
            return _fail(key, "cached_geometry_evidence_missing", started,
                         regen="SANITY_FAIL")
        try:
            with open(path, "rb") as fh:
                text = fh.read()
            measured = stl.measure(canon, text, verifier=verifier)
        except Exception as exc:
            return _fail(key, "cached_geometry_verification_failed: %s" % exc,
                         started, regen="SANITY_FAIL")
        ok = measured.get("regen_status") == "OK"
        hit.status = "ready" if ok else "failed"
        hit.source = "cache"
        hit.stl_url = "/api/geometry/%s.stl" % key
        hit.bbox_mm = measured["bbox_mm"]
        hit.volume_mm3 = measured["volume_mm3"]
        hit.triangles = measured["triangles"]
        hit.regen_status = measured.get("regen_status")
        hit.error = None if ok else "; ".join(measured.get("sanity_reasons", []))
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
        measured = stl.measure(canon, text, verifier=verifier)
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


def commit_to_document(space: DesignSpace, params: Dict[str, ParamValue], verifier=None) -> GeometryRef:
    """Persist an exact champion as verified defaults, then create a version.

    The write path is intentionally narrower than ``build_geometry``.  It only
    accepts a separately acknowledged workspace URL, derives a quantity-only
    update from a fresh configuration GET, requires a new source microversion,
    verifies both current and default values, sanity-checks the default STL, and
    creates a named version last.  Any unsupported CAD parameter or failed check
    stops the sequence; a partial write is reported and is never called a commit.
    """
    started = time.time()
    try:
        canon = canonicalize(space, params)
        key = geometry_key(space, canon)
    except Exception as exc:
        return _fail("invalid", "canonicalize failed: %s" % exc, started,
                     regen="ERROR")

    if os.environ.get("DARWIN_ONSHAPE_WRITE") != "1":
        return _fail(key, "onshape_write_disabled", started,
                     regen="NOT_ATTEMPTED", status="skipped")

    # A second acknowledgement is required because an API POST only accepts a
    # workspace, and the URL alone cannot establish that it is an isolated dev
    # workspace rather than the shared/prod document.
    if os.environ.get("DARWIN_ONSHAPE_WRITE_ISOLATED") != "1":
        return _fail(key, "onshape_write_requires_isolated_workspace", started,
                     regen="NOT_ATTEMPTED", status="skipped")

    url = _doc_url(space)
    target_url = (os.environ.get("DARWIN_ONSHAPE_WRITE_TARGET_URL") or "").strip()
    if not url:
        return _fail(key, "DARWIN_FIN_DOC_URL is not set", started,
                     regen="NOT_ATTEMPTED", status="skipped")
    if not target_url:
        return _fail(key, "onshape_write_target_not_acknowledged", started,
                     regen="NOT_ATTEMPTED", status="skipped")

    led = _get_ledger()
    if led.hard_stop():
        return _fail(key, "onshape_budget_reserve", started,
                     regen="NOT_ATTEMPTED", status="skipped")

    # This check must precede every network call. A missing verifier must never
    # become a real configuration write followed by a best-effort rollback.
    if verifier is None:
        return _fail(key, "domain_geometry_verifier_required", started,
                     regen="NOT_ATTEMPTED", status="skipped")

    before_calls = led.calls_total()
    write_attempted = False
    snapshot = None

    def failed(message: str, regen: str = "ERROR") -> GeometryRef:
        ref = _fail(key, message, started, regen=regen)
        ref.onshape_calls = led.calls_total() - before_calls
        return ref

    try:
        from cad.onshape_client import (build_configuration_restore,
                                        build_configuration_update,
                                        configuration_values,
                                        encode_configuration,
                                        parse_workspace_url,
                                        verify_configuration_update)

        doc_ref = parse_workspace_url(url)
        acknowledged_ref = parse_workspace_url(target_url)
        if doc_ref != acknowledged_ref:
            return failed("onshape_write_target_mismatch", "NOT_ATTEMPTED")
        did, wid, eid = doc_ref

        expected = _cad_values(space, canon)
        if not expected:
            return failed("onshape_write_has_no_cad_parameters", "NOT_ATTEMPTED")

        client = _get_client()
        before = client.get_configuration(did, wid, eid, purpose="commit_preflight")
        snapshot = before
        _configuration_cache[doc_ref] = before
        payload = build_configuration_update(before, expected)
        # The pre-write checkpoint is mandatory whenever writes are enabled.
        # A ledger refusal proves that no request was sent, so stop rather than
        # consuming the recovery reserve or claiming a partial write.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        pre_name = "darwin-pre-%s-%s" % (key[:8], stamp)
        pre_version_created = False
        try:
            pre_version = client.create_version(did, wid, pre_name,
                                                purpose="commit_recovery_version")
            if not isinstance(pre_version, dict) or not pre_version.get("id"):
                return failed("onshape_prewrite_version_failed", "NOT_ATTEMPTED")
            pre_version_created = True
        except BudgetExceeded as exc:
            return failed("onshape_write_blocked: onshape_budget_reserve: %s" % exc,
                          "NOT_ATTEMPTED")
        write_attempted = True
        try:
            client.update_configuration(did, wid, eid, payload, purpose="commit_update")
        except BudgetExceeded as exc:
            # Ledger.charge raises before sending, so this is not a partial
            # write even though the attempt flag was set conservatively first.
            write_attempted = False
            return failed("onshape_write_blocked: onshape_budget_reserve: %s" % exc,
                          "NOT_ATTEMPTED")
        after = client.get_configuration(did, wid, eid, purpose="commit_verify")
        _configuration_cache[doc_ref] = after
        verification = verify_configuration_update(before, after, expected)
        if not verification["ok"]:
            raise ValueError("configuration read-back failed")

        # Use an explicit configuration for deterministic geometry verification;
        # the read-back above independently proves that the defaults persisted.
        encoded = encode_configuration(expected, _cad_units(space))
        text = client.export_stl(did, wid, eid, configuration=encoded,
                                 purpose="commit_geometry_verify")
        measured = stl.measure(canon, text, verifier=verifier)
        if measured.get("regen_status") != "OK":
            reasons = "; ".join(measured.get("sanity_reasons", []))
            raise ValueError("geometry verification failed: %s" % reasons)

        version_name = "Darwin verified %s %s" % (key[:8], stamp)
        version = client.create_version(did, wid, version_name,
                                        purpose="commit_version")
        if not isinstance(version, dict) or not version.get("id"):
            raise ValueError("version creation returned no id")

        ref = GeometryRef(
            geometry_key=key, status="ready", source="onshape_config",
            stl_url="/api/geometry/%s.stl" % key,
            bbox_mm=measured["bbox_mm"], volume_mm3=measured["volume_mm3"],
            triangles=measured["triangles"],
            onshape_calls=led.calls_total() - before_calls,
            regen_status="OK",
            elapsed_ms=round((time.time() - started) * 1000.0, 2),
        )
        try:
            cache.store(ref, text)
        except Exception:
            pass
        return ref
    except Exception as exc:
        message = "%s: %s" % (type(exc).__name__, exc)
        if not write_attempted or snapshot is None:
            return failed("onshape_write_blocked: " + message, "NOT_ATTEMPTED")
        try:
            recovery_now = client.get_configuration(did, wid, eid,
                                                    purpose="commit_recovery_snapshot")
            restore_payload = build_configuration_restore(recovery_now, snapshot)
            client.update_configuration(did, wid, eid, restore_payload,
                                       purpose="commit_recovery_restore")
            restored = client.get_configuration(did, wid, eid,
                                                purpose="commit_recovery_verify")
            saved = configuration_values(snapshot)
            current_values = configuration_values(restored)
            bad = []
            for category in ("current", "defaults"):
                for pid, value in saved[category].items():
                    observed = current_values[category].get(pid)
                    if (isinstance(value, (int, float)) and not isinstance(value, bool)
                            and isinstance(observed, (int, float)) and not isinstance(observed, bool)):
                        matches = math.isclose(float(observed), float(value),
                                               rel_tol=1e-9, abs_tol=1e-9)
                    else:
                        matches = observed == value
                    if not matches:
                        bad.append("%s:%s" % (category, pid))
            if bad or restored.get("sourceMicroversion") == recovery_now.get("sourceMicroversion"):
                raise ValueError("restore verification failed" + (": " + ", ".join(bad) if bad else ""))
            _configuration_cache[doc_ref] = restored
            return failed("onshape_commit_failed; pre-write configuration restored: " + message,
                          "ERROR")
        except Exception as recovery_exc:
            if pre_version_created:
                manual = ("MANUAL RECOVERY REQUIRED: Onshape version graph → restore to the named "
                          "pre-write version '%s'." % pre_name)
            else:
                saved = configuration_values(snapshot)
                manual = ("MANUAL RECOVERY REQUIRED: no pre-write version was created because the "
                          "call budget refused it. In the Onshape version graph, restore the "
                          "pre-write quantity configuration values manually: %s" % saved)
            return failed("onshape_commit_failed: %s; recovery failed: %s; %s" %
                          (message, recovery_exc, manual), "PARTIAL_WRITE")


def preview_commit(space: DesignSpace, params: Dict[str, ParamValue]) -> Dict[str, object]:
    """Preview a write with a redacted target and no write-side effects."""
    try:
        canon = canonicalize(space, params)
        expected = _cad_values(space, canon)
        key = geometry_key(space, canon)
        from cad.onshape_client import configuration_values, parse_workspace_url
        url = _doc_url(space)
        if not url:
            raise ValueError("DARWIN_FIN_DOC_URL is not set")
        ref = parse_workspace_url(url)
        cfg = _configuration_cache.get(ref)
        calls = 0
        if cfg is None:
            led = _get_ledger()
            if led.hard_stop():
                raise BudgetExceeded("onshape_budget_reserve")
            did, wid, eid = ref
            cfg = _get_client().get_configuration(did, wid, eid,
                                                  purpose="commit_preview")
            _configuration_cache[ref] = cfg
            calls = 1
        current = configuration_values(cfg)["current"]
        diff = {pid: {"from": current.get(pid), "to": value}
                for pid, value in expected.items() if current.get(pid) != value}
        return {"target": space.name, "param_diff": diff,
                "expected_calls": calls,
                "checks_planned": ["configuration read-back", "STL geometry sanity", "named version"],
                "geometry_key": key}
    except Exception as exc:
        return {"target": space.name, "param_diff": {}, "expected_calls": 0,
                "checks_planned": [], "error": "%s: %s" % (type(exc).__name__, exc)}


def export_print_package(space: DesignSpace, params: Dict[str, ParamValue],
                         out_dir: str, design_id: Optional[str] = None,
                         score: Optional[object] = None,
                         verifier=None) -> Optional[str]:
    """Build a deterministic offline print bundle for a measured design.

    ``design_id`` and ``score`` are additive so old callers remain source
    compatible; both are required to produce the requested auditable label.
    Geometry is obtained only through the normal cache/build path.
    """
    from cad.print_package import export_print_package as _export
    return _export(space, params, out_dir, design_id=design_id, score=score,
                   verifier=verifier)


def discover_design_space(doc_url: str, probe: bool = False) -> DesignSpace:
    raise NotImplementedError("auto-discovery lands with Tier 3")


# ---- Plan v4: Variable features (the live morph). Thin wrappers over cad.variables (B.7). ----

def list_variables(doc_url: str) -> Dict[str, Dict[str, object]]:
    """Live Variable values in the document's Part Studio. 1 call. Raises OnshapeError on HTTP failure."""
    from cad import variables
    return variables.list_variables(doc_url)


def apply_values(doc_url: str, params: Dict[str, ParamValue], units: Dict[str, str]) -> GeometryRef:
    """Write changed params into their Variable features so open tabs morph. Never raises."""
    from cad import variables
    return variables.apply_values(doc_url, params, units)


def create_version(doc_url: str, name: str) -> Optional[str]:
    """Named version of the workspace; None if refused or failed."""
    from cad import variables
    return variables.create_version(doc_url, name)

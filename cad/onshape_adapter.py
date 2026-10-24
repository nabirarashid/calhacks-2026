"""Duck-typed B.4 Onshape adapter pending shared manifest/adapters freeze."""
import os
import re
import time
import json
from copy import deepcopy

from shared.contracts import DesignSpace, GeometryRef, canonicalize, geometry_key
from cad import api
from cad.export_step import cached_step, content_key, store_step
from cad.ledger import BudgetExceeded
from cad.probe import MAX_REGENERATIONS, generate_cases, probe as run_probe, probe_cache_key

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _get(obj, key, default=None):
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


class OnshapeCadAdapter:
    """Adapter over the v1 CAD functions with a runtime-only manifest bridge."""

    def __init__(self, client=None, ledger=None, verifier=None):
        self.client = client
        self.ledger = ledger
        self.verifier = verifier
        self._run_call_starts = {}

    def _ledger(self):
        return self.ledger or getattr(self.client, "ledger", None) or api._get_ledger()

    def _run_key(self, manifest):
        cad = _get(manifest, "cad", {}) or {}
        return (id(manifest), str(_get(manifest, "project_id", "legacy")),
                str(_get(manifest, "revision", "0")),
                str(_get(cad, "source_microversion", "")))

    def _run_limit(self, manifest):
        authority = _get(manifest, "authority", {}) or {}
        limit = _get(authority, "max_onshape_calls_per_run", 12)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("invalid authority.max_onshape_calls_per_run")
        return limit

    def _run_calls(self, manifest, ledger):
        total = ledger.calls_total()
        key = self._run_key(manifest)
        if key not in self._run_call_starts:
            self._run_call_starts[key] = total
        return max(0, total - self._run_call_starts[key])

    def _call_room(self, manifest, ledger, worst_case=1):
        return self._run_calls(manifest, ledger) + worst_case <= self._run_limit(manifest)

    def _binding_url(self, manifest, write=False):
        binding = _get(manifest, "cad", {})
        ref = _get(binding, "write_target_ref" if write else "doc_ref")
        if not isinstance(ref, str) or not _ENV_NAME.fullmatch(ref):
            raise ValueError("CAD binding must name an environment variable")
        value = os.environ.get(ref)
        if not value and not write and ref in ("DARWIN_DOC_FIN", "DARWIN_FIN_DOC_URL"):
            value = os.environ.get("DARWIN_FIN_DOC_URL") or os.environ.get("DARWIN_DOC_FIN")
        if not value:
            raise ValueError("CAD binding environment variable is unset")
        return value.strip()

    def _runtime_space(self, manifest, write=False):
        space = _get(manifest, "design_space")
        if space is None:
            raise ValueError("manifest lacks design_space")
        if isinstance(space, dict):
            space = deepcopy(space)
            space.setdefault("source", {})["doc_url"] = self._binding_url(manifest, write=write)
            return DesignSpace.model_validate(space)
        copier = getattr(space.source, "model_copy", None) or space.source.copy
        source = copier(update={"doc_url": self._binding_url(manifest, write=write)}, deep=True)
        copier = getattr(space, "model_copy", None) or space.copy
        return copier(update={"source": source}, deep=True)

    def _client(self):
        if self.client is None:
            self.client = api._get_client()
        return self.client

    def _bound_verifier(self, manifest):
        binder = getattr(self.verifier, "bind", None)
        return binder(manifest) if callable(binder) else self.verifier

    def _current_microversion(self, manifest):
        from cad.onshape_client import parse_doc_url
        did, wid, eid = parse_doc_url(self._binding_url(manifest))
        return self._client().get_configuration(did, wid, eid, purpose="stale_guard").get("sourceMicroversion")

    def _check_fresh(self, manifest):
        expected = _get(_get(manifest, "cad", {}), "source_microversion")
        if not expected:
            return "stale_revision_missing"
        try:
            actual = self._current_microversion(manifest)
        except Exception:
            return "stale_revision_unverified"
        return None if actual == expected else "stale_revision"

    def capability(self):
        # Plain dict until AdapterCapability is supplied by shared/adapters.py.
        return {"provider": "onshape", "inspect": True, "probe": True,
                "build_formats": ["stl", "step"], "commit": True}

    def inspect(self, doc_ref=None):
        from cad.inspect import parse_inventory, save_sanitized_raw
        from cad.onshape_client import parse_doc_url
        if not isinstance(doc_ref, str) or not _ENV_NAME.fullmatch(doc_ref):
            raise ValueError("inspect doc_ref must name an environment variable")
        url = os.environ.get(doc_ref)
        if not url and doc_ref in ("DARWIN_DOC_FIN", "DARWIN_FIN_DOC_URL"):
            url = os.environ.get("DARWIN_FIN_DOC_URL") or os.environ.get("DARWIN_DOC_FIN")
        if not url:
            raise ValueError("CAD binding environment variable is unset")
        did, wid, eid = parse_doc_url(url)
        client = self._client()
        ledger = getattr(client, "ledger", None)
        before = ledger.calls_total() if ledger is not None else None
        elements = client.get_elements(did, wid, purpose="inspect")
        config = client.get_configuration(did, wid, eid, purpose="inspect")
        features = client.get_features(did, wid, eid, purpose="inspect")
        parts = client.get_parts(did, wid, eid, purpose="inspect")
        mass_properties = client.get_mass_properties(did, wid, eid, purpose="inspect")
        raw = {"elements": elements, "configuration": config,
               "features": features, "parts": parts,
               "mass_properties": mass_properties,
               "export_formats": ["stl", "step"]}
        snapshot_name = re.sub(r"[^A-Za-z0-9_-]", "_", doc_ref)[:80]
        save_sanitized_raw(raw, os.path.join(".darwin", "inspect", snapshot_name + ".json"))
        calls = ledger.calls_total() - before if ledger is not None else 5
        if calls > 6:
            raise BudgetExceeded("inspect exceeded six Onshape calls")
        return parse_inventory(raw, onshape_calls=calls)

    def probe(self, manifest, cases):
        space = _get(manifest, "design_space")
        specs = [p.model_dump() if hasattr(p, "model_dump") else p.dict() if hasattr(p, "dict") else dict(p)
                 for p in _get(space, "parameters", [])]
        seed = {p["name"]: p.get("default") for p in specs if p.get("name")}
        project_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(_get(manifest, "project_id", "probe")))[:80] or "probe"
        source = _get(space, "source", {})
        cad_binding = _get(manifest, "cad", {})
        namespace = "%s:%s:%s:%s" % (
            project_id, _get(space, "id", ""), _get(source, "model_revision", ""),
            _get(cad_binding, "source_microversion", ""))
        cache_name = re.sub(r"[^A-Za-z0-9_-]", "_", namespace)[:100]
        cache_name += "-" + probe_cache_key({}, namespace)[:12]
        cache_path = os.path.join(".darwin", "probes", cache_name + ".json")
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                probe_cache = json.load(fh)
            if not isinstance(probe_cache, dict):
                probe_cache = {}
        except (OSError, ValueError):
            probe_cache = {}
        def regenerate(values):
            ref = self.build_geometry(manifest, values, fmt="stl")
            return ref.model_dump() if hasattr(ref, "model_dump") else ref.dict() if hasattr(ref, "dict") else dict(ref)
        supplied = list(cases or generate_cases(specs, seed, limit=MAX_REGENERATIONS))[:MAX_REGENERATIONS]
        ledger = self._ledger()
        self._run_calls(manifest, ledger)
        uncached_regenerations = 0
        rows = []
        for index, case in enumerate(supplied):
            values = case.get("params", case) if isinstance(case, dict) else seed
            if not isinstance(values, dict):
                continue
            key = probe_cache_key(values, namespace)
            cached = key in probe_cache
            if not cached:
                if uncached_regenerations >= MAX_REGENERATIONS:
                    break
                # One configured STL request may use an authenticated request
                # and one redirect hop. Do not start if both cannot fit.
                if not self._call_room(manifest, ledger, worst_case=2):
                    break
                uncached_regenerations += 1
            generated = run_probe([], values, regenerate, cache=probe_cache,
                                  limit=1, cache_namespace=namespace)
            if self._run_calls(manifest, ledger) > self._run_limit(manifest):
                generated = [{"case": "call_limit", "params": dict(values),
                              "geometry": {"status": "skipped", "error": "max_onshape_calls_per_run"},
                              "evidence": {"passed": False, "failure_reason": "call_limit",
                                           "cached": False}}]
            if generated:
                generated[0]["case"] = (case.get("case") if isinstance(case, dict)
                                        else None) or "case:%d" % index
                rows.extend(generated)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        temp_path = cache_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(probe_cache, fh, sort_keys=True)
            fh.write("\n")
        os.replace(temp_path, cache_path)
        return rows

    def build_geometry(self, manifest, params, *, fmt="stl"):
        started = time.time()
        if fmt not in ("stl", "step"):
            return GeometryRef(geometry_key="invalid", status="failed", source="none",
                               error="unsupported_geometry_format")
        if self.verifier is None:
            return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                               error="domain_geometry_verifier_required",
                               regen_status="NOT_ATTEMPTED")
        try:
            ledger = self._ledger()
            operation_before = ledger.calls_total()
            if not self._call_room(manifest, ledger, worst_case=1):
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
        except Exception as exc:
            return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                               error="onshape_ledger_unavailable: %s" % type(exc).__name__)
        stale = self._check_fresh(manifest)
        if stale:
            return GeometryRef(geometry_key="stale", status="failed", source="none", error=stale,
                               onshape_calls=ledger.calls_total()-operation_before)
        try:
            if not self._call_room(manifest, ledger, worst_case=2):
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
            space = self._runtime_space(manifest)
            canon = canonicalize(space, params)
            key = geometry_key(space, canon)
            if fmt == "stl":
                ref = api.build_geometry(space, params,
                                         verifier=self._bound_verifier(manifest))
                if self._run_calls(manifest, ledger) > self._run_limit(manifest):
                    return GeometryRef(geometry_key=key, status="skipped", source="none",
                                       error="max_onshape_calls_per_run")
                ref.onshape_calls = ledger.calls_total() - operation_before
                return ref
            source_revision = _get(_get(manifest, "cad", {}), "source_microversion", "")
            step_key = content_key(space.id, space.source.model_revision, canon, source_revision)
            hit = cached_step(step_key)
            if hit:
                verified_stl = api.build_geometry(space, params, allow_network=False,
                                                  verifier=self._bound_verifier(manifest))
                if verified_stl.status != "ready" or verified_stl.regen_status != "OK":
                    verified_stl.onshape_calls = ledger.calls_total() - operation_before
                    return verified_stl
                self.last_step_path = hit
                return GeometryRef(geometry_key=key, status="ready", source="cache",
                                   bbox_mm=verified_stl.bbox_mm,
                                   volume_mm3=verified_stl.volume_mm3,
                                   triangles=verified_stl.triangles,
                                   regen_status="OK",
                                   onshape_calls=ledger.calls_total()-operation_before,
                                   elapsed_ms=round((time.time()-started)*1000, 2))
            verified_stl = api.build_geometry(space, params,
                                              verifier=self._bound_verifier(manifest))
            if verified_stl.status != "ready" or verified_stl.regen_status != "OK":
                verified_stl.onshape_calls = ledger.calls_total() - operation_before
                return verified_stl
            if self._run_calls(manifest, ledger) > self._run_limit(manifest):
                return GeometryRef(geometry_key=key, status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
            led = self._ledger()
            if led.hard_stop():
                return GeometryRef(geometry_key=key, status="skipped", source="none",
                                   error="onshape_budget_reserve")
            from cad.onshape_client import parse_doc_url, encode_configuration
            did, wid, eid = parse_doc_url(self._binding_url(manifest))
            cfg = encode_configuration(api._cad_values(space, canon), api._cad_units(space))
            # Reserve for POST, at least one poll, output download and one
            # possible redirect per request. This bounds the full STEP phase.
            remaining = self._run_limit(manifest) - self._run_calls(manifest, led)
            max_polls = min(12, remaining // 2 - 2)
            if max_polls < 1:
                return GeometryRef(geometry_key=key, status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
            data = self._client().export_step(did, wid, eid, configuration=cfg,
                                              purpose="build_step", max_polls=max_polls)
            if self._run_calls(manifest, led) > self._run_limit(manifest):
                return GeometryRef(geometry_key=key, status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
            if not (data.startswith(b"ISO-10303") or data.startswith(b"PK\x03\x04")):
                raise ValueError("STEP export has an unrecognized file signature")
            path = store_step(step_key, data)
            # GeometryRef v1 has no STEP path field. Keep its shape unchanged;
            # the runtime cache lookup returns the path to consumers.
            ref = GeometryRef(geometry_key=key, status="ready", source="onshape_config",
                              bbox_mm=verified_stl.bbox_mm,
                              volume_mm3=verified_stl.volume_mm3,
                              triangles=verified_stl.triangles,
                              regen_status="OK",
                              onshape_calls=led.calls_total()-operation_before,
                              elapsed_ms=round((time.time()-started)*1000, 2))
            self.last_step_path = path
            return ref
        except BudgetExceeded:
            return GeometryRef(geometry_key=locals().get("key", "invalid"), status="skipped",
                               source="none", error="onshape_budget_reserve",
                               onshape_calls=(ledger.calls_total()-operation_before
                                              if "ledger" in locals() and "operation_before" in locals()
                                              else 0))
        except Exception as exc:
            return GeometryRef(geometry_key=locals().get("key", "invalid"), status="failed",
                               source="none", error="%s: %s" % (type(exc).__name__, exc),
                               onshape_calls=(ledger.calls_total()-operation_before
                                              if "ledger" in locals() and "operation_before" in locals()
                                              else 0))

    def preview_commit(self, manifest, params):
        try:
            return api.preview_commit(self._runtime_space(manifest, write=True), params)
        except Exception as exc:
            return {"target": "redacted", "param_diff": {}, "expected_calls": 0,
                    "checks_planned": [], "error": "%s: %s" % (type(exc).__name__, exc)}

    def commit(self, manifest, params, approval=None):
        if self.verifier is None:
            return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                               error="domain_geometry_verifier_required",
                               regen_status="NOT_ATTEMPTED")
        try:
            authority = _get(manifest, "authority", {}) or {}
            permitted = _get(authority, "permitted", []) or []
            maturity = _get(authority, "maturity")
            if hasattr(maturity, "value"):
                maturity = maturity.value
            if maturity not in (4, "4") or "write" not in permitted:
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="write_requires_maturity_4_and_permission")
            if not isinstance(approval, dict) or approval.get("status") != "approved":
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="approved_bound_approval_required")
            bindings = {
                "project_id": _get(manifest, "project_id"),
                "manifest_revision": _get(manifest, "revision"),
                "cad_source_microversion": _get(_get(manifest, "cad", {}), "source_microversion"),
            }
            expected_hash = _get(manifest, "manifest_hash")
            if not expected_hash:
                expected_hash = _get(authority, "manifest_hash")
            for field, expected in bindings.items():
                if expected is None or approval.get(field) != expected:
                    return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                       error="approval_binding_mismatch:%s" % field)
            if (not expected_hash or approval.get("manifest_hash") != expected_hash
                    or not isinstance(approval.get("evidence_hash"), str)
                    or not approval["evidence_hash"].strip()):
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="approval_binding_mismatch:manifest_or_evidence_hash")
            space_for_approval = _get(manifest, "design_space")
            if isinstance(space_for_approval, dict):
                space_for_approval = DesignSpace.model_validate(space_for_approval)
            canonical_params = canonicalize(space_for_approval, params)
            expected_geometry_key = geometry_key(space_for_approval, canonical_params)
            approved_params = approval.get("canonical_params", approval.get("params"))
            if not isinstance(approved_params, dict) or approved_params != canonical_params:
                return GeometryRef(geometry_key=expected_geometry_key, status="skipped", source="none",
                                   error="approval_binding_mismatch:params")
            approved_geometry = approval.get("geometry")
            approved_key = approval.get("geometry_key")
            if approved_key is None and isinstance(approved_geometry, dict):
                approved_key = approved_geometry.get("geometry_key")
            if approved_key != expected_geometry_key:
                return GeometryRef(geometry_key=expected_geometry_key, status="skipped", source="none",
                                   error="approval_binding_mismatch:geometry_key")
            if (not isinstance(approved_geometry, dict)
                    or approved_geometry.get("status") != "ready"
                    or approved_geometry.get("geometry_key") != expected_geometry_key
                    or approved_geometry.get("regen_status") not in (None, "OK")):
                return GeometryRef(geometry_key=expected_geometry_key, status="skipped", source="none",
                                   error="approval_binding_mismatch:ready_geometry")
            solver = approval.get("solver")
            if (not isinstance(solver, list) or not solver
                    or any(not isinstance(row, dict) or not row.get("adapter_id")
                           or not row.get("version") for row in solver)):
                return GeometryRef(geometry_key=expected_geometry_key, status="skipped", source="none",
                                   error="approval_binding_mismatch:solver")
            target_url = self._binding_url(manifest, write=True)
            configured_target = (os.environ.get("DARWIN_ONSHAPE_WRITE_TARGET_URL") or "").strip()
            if configured_target != target_url:
                return GeometryRef(geometry_key="invalid", status="skipped", source="none",
                                   error="onshape_write_target_not_acknowledged")
            from cad.onshape_client import parse_workspace_url
            parse_workspace_url(target_url)
            ledger = self._ledger()
            operation_before = ledger.calls_total()
            if not self._call_room(manifest, ledger, worst_case=11):
                return GeometryRef(geometry_key=expected_geometry_key, status="skipped", source="none",
                                   error="max_onshape_calls_per_run")
            stale = self._check_fresh(manifest)
            if stale:
                return GeometryRef(geometry_key="stale", status="failed", source="none", error=stale,
                                   onshape_calls=ledger.calls_total()-operation_before)
            space = self._runtime_space(manifest, write=True)
            ref = api.commit_to_document(space, params,
                                         verifier=self._bound_verifier(manifest))
            if hasattr(ref, "onshape_calls"):
                ref.onshape_calls = ledger.calls_total() - operation_before
            return ref
        except Exception as exc:
            return GeometryRef(geometry_key="invalid", status="failed", source="none",
                               error="%s: %s" % (type(exc).__name__, exc))

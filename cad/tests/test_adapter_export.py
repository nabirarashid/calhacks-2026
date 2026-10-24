import os

import pytest

from cad import api
from cad.ledger import BudgetExceeded, Ledger
from cad.onshape_adapter import OnshapeCadAdapter
from cad.onshape_client import OnshapeClient
from shared.contracts import CadSource, DesignSpace, ParamSpec, geometry_key


class Response:
    status_code = 200
    headers = {}
    text = "solid fake\nendsolid fake"
    content = b"ISO-10303-21;\nEND-ISO-10303-21;"
    def __init__(self, data): self.data = data
    def json(self): return self.data


class Session:
    def __init__(self, responses): self.responses = list(responses); self.calls = []; self.auth = None; self.cookies = type("C", (), {"clear": lambda self: None})()
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        return value
    def close(self): pass


def test_cross_origin_redirect_does_not_forward_auth(monkeypatch, tmp_path):
    client, original, ledger = make_client(tmp_path, [Response({})])
    redirect = Response({})
    redirect.status_code = 302
    redirect.headers = {"Location": "https://objects.example/download"}
    original.responses = [redirect]
    external = Session([Response({})])
    monkeypatch.setattr("cad.onshape_client.requests.Session", lambda: external)
    client.request("GET", "/export", "build", follow_redirect=True)
    assert len(external.calls) == 1
    assert "Authorization" not in external.calls[0][2].get("headers", {})
    assert ledger.calls_total() == 2


def test_cross_origin_redirect_rejects_cleartext(monkeypatch, tmp_path):
    client, original, _ledger = make_client(tmp_path, [Response({})])
    redirect = Response({})
    redirect.status_code = 302
    redirect.headers = {"Location": "http://objects.example/download"}
    original.responses = [redirect]
    with pytest.raises(Exception, match="insecure external redirect"):
        client.request("GET", "/export", "build", follow_redirect=True)


def make_client(tmp_path, responses, remaining=20, reserve=0):
    ledger = Ledger("step-test", calls_remaining=remaining, reserve=reserve, root=str(tmp_path))
    client = OnshapeClient(access_key="a", secret_key="b", ledger=ledger,
                           base="https://mock.invalid/api/v10")
    session = Session(responses)
    client._session = session
    return client, session, ledger


def manifest():
    space = DesignSpace(id="adapter-test", name="Adapter", scorer="x",
                        parameters=[ParamSpec(name="length", kind="continuous", unit="mm",
                                              min=1, max=10, default=2)],
                        source=CadSource(kind="onshape"))
    return {"cad": {"provider": "onshape", "doc_ref": "CAD_TEST_DOC",
                     "source_microversion": "mv1"}, "design_space": space}


def test_env_name_resolution_and_raw_url_rejection(monkeypatch):
    adapter = OnshapeCadAdapter()
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    assert adapter._binding_url(manifest()).endswith("/e/e")
    bad = {"cad": {"doc_ref": "https://cad.onshape.com/documents/d/w/w/e/e"}}
    with pytest.raises(ValueError, match="environment variable"):
        adapter._binding_url(bad)


def test_stale_microversion_fails_closed_before_build(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    class Client:
        def get_configuration(self, *args, **kwargs): return {"sourceMicroversion": "mv2"}
    adapter = OnshapeCadAdapter(client=Client(), verifier=object())
    ref = adapter.build_geometry(manifest(), {"length": 2}, fmt="stl")
    assert ref.status == "failed" and ref.error == "stale_revision"


def test_inspect_and_probe_hooks_use_local_helpers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    class Client:
        def get_elements(self, *args, **kwargs): return [{"name": "Part Studio"}]
        def get_configuration(self, *args, **kwargs):
            return {"sourceMicroversion": "mv1", "configurationParameters": [],
                    "currentConfiguration": []}
        def get_features(self, *args, **kwargs): return {"features": []}
        def get_parts(self, *args, **kwargs): return []
        def get_mass_properties(self, *args, **kwargs): return {"bodies": {}}
    adapter = OnshapeCadAdapter(client=Client())
    inventory = adapter.inspect("CAD_TEST_DOC")
    assert inventory["provider"] == "onshape" and inventory["onshape_calls"] == 5
    assert (tmp_path / ".darwin" / "inspect" / "CAD_TEST_DOC.json").exists()
    monkeypatch.setattr(adapter, "build_geometry", lambda *args, **kwargs: type("R", (), {
        "model_dump": lambda self: {"status": "ready", "bbox_mm": [0, 0, 0, 1, 1, 1]}
    })())
    rows = adapter.probe(manifest(), [{"length": 2}])
    assert rows and all("passed" in row["evidence"] for row in rows)


def test_preview_and_commit_delegate_only_after_fresh_guard(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    monkeypatch.setenv("CAD_TEST_WRITE", "https://cad.onshape.com/documents/d/w/target/e/e")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_TARGET_URL",
                       "https://cad.onshape.com/documents/d/w/target/e/e")
    monkeypatch.setattr(OnshapeCadAdapter, "_check_fresh", lambda *a: None)
    adapter = OnshapeCadAdapter()
    sentinel = {"target": "Adapter"}
    monkeypatch.setattr(api, "preview_commit", lambda *a: sentinel)
    m = manifest()
    m["cad"]["write_target_ref"] = "CAD_TEST_WRITE"
    assert adapter.preview_commit(m, {"length": 2}) is sentinel
    monkeypatch.setattr(OnshapeCadAdapter, "_check_fresh", lambda *a: "stale_revision")
    # Preview is bounded to its own zero-or-one target read; revision drift is
    # enforced on build and commit, not with a second source read in preview.
    assert adapter.preview_commit(m, {"length": 2}) is sentinel
    m.update({"project_id": "p", "revision": 1, "manifest_hash": "mh",
              "authority": {"maturity": 4, "permitted": ["write"]}})
    key = geometry_key(m["design_space"], {"length": 2})
    approval = {"status": "approved", "project_id": "p", "manifest_revision": 1,
                "cad_source_microversion": "mv1", "manifest_hash": "mh",
                "evidence_hash": "eh", "canonical_params": {"length": 2},
                "geometry_key": key,
                "geometry": {"status": "ready", "regen_status": "OK",
                             "geometry_key": key},
                "solver": [{"adapter_id": "test", "version": "1"}]}
    assert OnshapeCadAdapter(verifier=object()).commit(
        m, {"length": 2}, approval).error == "stale_revision"


def test_commit_uses_only_manifest_acknowledged_target(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/source/e/e")
    target = "https://cad.onshape.com/documents/d/w/target/e/e"
    monkeypatch.setenv("CAD_TEST_WRITE", target)
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_TARGET_URL", target)
    monkeypatch.setattr(OnshapeCadAdapter, "_check_fresh", lambda *a: None)
    seen = {}
    def commit(space, params, verifier=None):
        seen["url"] = space.source.doc_url
        seen["verifier"] = verifier
        return "committed"
    monkeypatch.setattr(api, "commit_to_document", commit)
    m = manifest()
    m["cad"]["write_target_ref"] = "CAD_TEST_WRITE"
    m["project_id"] = "adapter-project"
    m["revision"] = 3
    m["manifest_hash"] = "manifest-hash"
    m["authority"] = {"maturity": 4, "permitted": ["write"]}
    verifier = object()
    key = geometry_key(m["design_space"], {"length": 2})
    approval = {"status": "approved", "project_id": "adapter-project",
                "manifest_revision": 3, "cad_source_microversion": "mv1",
                "manifest_hash": "manifest-hash", "evidence_hash": "evidence-hash",
                "canonical_params": {"length": 2}, "geometry_key": key,
                "geometry": {"status": "ready", "regen_status": "OK",
                             "geometry_key": key},
                "solver": [{"adapter_id": "test", "version": "1"}]}
    assert OnshapeCadAdapter(verifier=verifier).commit(m, {"length": 2}, approval) == "committed"
    assert seen["url"] == target
    assert seen["verifier"] is verifier


def test_commit_requires_bound_approval_before_write(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/source/e/e")
    monkeypatch.setenv("CAD_TEST_WRITE", "https://cad.onshape.com/documents/d/w/target/e/e")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_TARGET_URL", "https://cad.onshape.com/documents/d/w/target/e/e")
    monkeypatch.setattr(OnshapeCadAdapter, "_check_fresh", lambda *a: None)
    m = manifest()
    m["cad"]["write_target_ref"] = "CAD_TEST_WRITE"
    m["project_id"] = "p"
    m["revision"] = 2
    m["manifest_hash"] = "mh"
    m["authority"] = {"maturity": 3, "permitted": ["write"]}
    adapter = OnshapeCadAdapter(verifier=object())
    assert adapter.commit(m, {"length": 2}, {}).error == "write_requires_maturity_4_and_permission"
    m["authority"]["maturity"] = 4
    assert adapter.commit(m, {"length": 2}, None).error == "approved_bound_approval_required"
    called = []
    monkeypatch.setattr(api, "commit_to_document", lambda *a, **k: called.append(True))
    approval = {"status": "approved", "project_id": "p", "manifest_revision": 2,
                "cad_source_microversion": "mv1", "manifest_hash": "mh",
                "evidence_hash": "eh", "canonical_params": {"length": 3}}
    result = adapter.commit(m, {"length": 2}, approval)
    assert result.error == "approval_binding_mismatch:params"
    assert not called


@pytest.mark.parametrize("fmt", ["stl", "step"])
def test_build_dispatches_format(monkeypatch, tmp_path, fmt):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    monkeypatch.setattr(OnshapeCadAdapter, "_check_fresh", lambda *a: None)
    expected = type("Ref", (), {"status": "ready", "regen_status": "OK",
                                  "bbox_mm": None, "volume_mm3": None,
                                  "triangles": None, "onshape_calls": 0})()
    if fmt == "stl":
        monkeypatch.setattr(api, "build_geometry", lambda *a, **k: expected)
        adapter = OnshapeCadAdapter(verifier=object())
    else:
        # A cache hit proves dispatch and keeps this test independent of HTTP.
        import cad.onshape_adapter as adapter_module
        monkeypatch.setattr(adapter_module, "cached_step", lambda key: "/tmp/cached.step")
        monkeypatch.setattr(api, "build_geometry", lambda *a, **k: expected)
        adapter = OnshapeCadAdapter(verifier=object())
    result = adapter.build_geometry(manifest(), {"length": 2}, fmt=fmt)
    assert result is expected if fmt == "stl" else result.status == "ready"


def test_step_cache_key_includes_source_microversion():
    from cad.export_step import content_key
    args = ("space", "r1", {"length": 2})
    assert content_key(*args, source_microversion="mv1") != content_key(
        *args, source_microversion="mv2")


def test_probe_enforces_authority_call_ceiling(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    ledger = Ledger("probe-cap", calls_remaining=100, root=str(tmp_path / "ledger"))
    adapter = OnshapeCadAdapter(ledger=ledger, verifier=object())
    monkeypatch.setattr(adapter, "_check_fresh", lambda *a: None)
    def build(_manifest, values, fmt="stl"):
        ledger.charge("probe-test", "GET", "fake")
        ledger.charge("probe-test", "GET", "redirect")
        return type("Ref", (), {"model_dump": lambda self: {
            "status": "ready", "bbox_mm": [0, 0, 0, 1, 1, 1],
            "onshape_calls": 2, "units": "mm"}})()
    monkeypatch.setattr(adapter, "build_geometry", build)
    m = manifest()
    m["project_id"] = "p"
    m["authority"] = {"max_onshape_calls_per_run": 3}
    rows = adapter.probe(m, [{"length": 2}, {"length": 3}, {"length": 4}])
    assert len(rows) == 1
    assert ledger.calls_total() == 2


def test_call_budget_scope_resets_for_new_manifest_revision(tmp_path):
    ledger = Ledger("run-scope", calls_remaining=100, root=str(tmp_path / "ledger"))
    adapter = OnshapeCadAdapter(ledger=ledger, verifier=object())
    first = manifest()
    first.update({"project_id": "p", "revision": 1})
    assert adapter._run_calls(first, ledger) == 0
    ledger.charge("test", "GET", "fake")
    assert adapter._run_calls(first, ledger) == 1
    second = dict(first, revision=2)
    assert adapter._run_calls(second, ledger) == 0


def test_commit_approval_requires_ready_geometry_and_solver(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/source/e/e")
    monkeypatch.setenv("CAD_TEST_WRITE", "https://cad.onshape.com/documents/d/w/target/e/e")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_TARGET_URL",
                       "https://cad.onshape.com/documents/d/w/target/e/e")
    m = manifest()
    m["cad"]["write_target_ref"] = "CAD_TEST_WRITE"
    m.update({"project_id": "p", "revision": 2, "manifest_hash": "mh",
              "authority": {"maturity": 4, "permitted": ["write"]}})
    key = geometry_key(m["design_space"], {"length": 2})
    approval = {"status": "approved", "project_id": "p", "manifest_revision": 2,
                "cad_source_microversion": "mv1", "manifest_hash": "mh",
                "evidence_hash": "eh", "canonical_params": {"length": 2},
                "geometry_key": key}
    adapter = OnshapeCadAdapter(verifier=object())
    assert adapter.commit(m, {"length": 2}, approval).error == \
        "approval_binding_mismatch:ready_geometry"
    approval["geometry"] = {"status": "ready", "regen_status": "OK",
                            "geometry_key": key}
    assert adapter.commit(m, {"length": 2}, approval).error == \
        "approval_binding_mismatch:solver"


def test_build_and_commit_require_domain_verifier_without_network(monkeypatch):
    monkeypatch.setenv("CAD_TEST_DOC", "https://cad.onshape.com/documents/d/w/w/e/e")
    adapter = OnshapeCadAdapter()
    built = adapter.build_geometry(manifest(), {"length": 2})
    committed = adapter.commit(manifest(), {"length": 2})
    assert built.error == "domain_geometry_verifier_required"
    assert committed.error == "domain_geometry_verifier_required"


def test_step_translation_done_failed_timeout_and_budget(tmp_path):
    client, session, ledger = make_client(tmp_path, [
        Response({"id": "private-id"}), Response({"requestState": "DONE", "resultExternalDataIds": ["f"]}),
        Response({}),
    ])
    payload = client.export_step("d", "w", "e", timeout_s=1, poll_interval_s=0, max_polls=2)
    assert payload.startswith(b"ISO-10303")
    assert [x[0] for x in session.calls] == ["POST", "GET", "GET"]
    assert "private-id" not in open(ledger.path).read()

    failed, _, _ = make_client(tmp_path, [Response({"id": "id"}), Response({"requestState": "FAILED"})])
    with pytest.raises(Exception, match="translation failed"):
        failed.export_step("d", "w", "e", timeout_s=1, poll_interval_s=0)

    timeout, _, _ = make_client(tmp_path, [Response({"id": "id"}), Response({"requestState": "ACTIVE"})])
    with pytest.raises(TimeoutError):
        timeout.export_step("d", "w", "e", timeout_s=0, poll_interval_s=0, max_polls=1)

    budget, _, _ = make_client(tmp_path, [], remaining=1, reserve=1)
    with pytest.raises(BudgetExceeded):
        budget.export_step("d", "w", "e")

"""Deterministic evidence and approval behavior."""
import json
from types import SimpleNamespace

import pytest

from backend import evidence


def design(**kwargs):
    base = {
        "design_id": "design_1", "param_hash": "hash_1",
        "params": {"span": 4.0},
        "score": {"feasible": True, "metrics": {"drag": 2.0, "mass": 8.0}},
        "geometry": {"status": "ready", "regen_status": "OK", "geometry_key": "geo_1"},
    }
    base.update(kwargs)
    return base


def summary(**kwargs):
    base = {
        "status": "complete",
        "goal": {"source_text": "keep it < light", "assumptions": ["PLA & aluminum"],
                 "constraints": [
                     {"ref": "drag", "op": "<=", "value": 2.0, "hard": True},
                     {"ref": "mass", "op": ">=", "value": 8.0, "hard": False},
                     {"ref": "param:span", "op": "==", "value": 4.0},
                 ]},
        "seed_design": {"params": {"span": 3.0, "root": 2.0}},
        "hifi_check": {"feasible": True}, "budget": {"used": 4}, "degradations": [],
    }
    base.update(kwargs)
    return base


def test_requirement_operators_margins_and_missing_values():
    rows = evidence.requirement_results(summary()["goal"], design())
    assert [(r["passed"], r["margin"]) for r in rows] == [(True, 0.0), (True, 0.0), (True, -0.0)]
    missing = evidence.requirement_results(
        {"constraints": [{"ref": "unknown", "op": "<=", "value": 1}]}, design())
    assert missing[0]["actual"] is None and missing[0]["margin"] is None and not missing[0]["passed"]
    fail = evidence.requirement_results(
        {"constraints": [{"ref": "drag", "op": "<=", "value": 1}]}, design())[0]
    assert fail["margin"] == -1 and not fail["passed"]


@pytest.mark.parametrize("changes", [
    {"score": {"feasible": False, "metrics": {"drag": 2.0, "mass": 8.0}}},
    {"geometry": {"status": "ready", "regen_status": "ERROR"}},
    {"geometry": {"status": "missing", "regen_status": "OK"}},
])
def test_approval_rejects_invalid_design(changes, tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        evidence.approve("run_1", summary(), design(**changes))
    assert not (tmp_path / "approvals" / "run_1.json").exists()


def test_approval_persists_and_is_bound_to_design(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))
    d = design()
    record = evidence.approve("run_1", summary(), d, "  Pat <Engineer>  ")
    assert record["approved_by"] == "Pat <Engineer>"
    assert evidence.load_approval("run_1", d) == record
    assert evidence.load_approval("run_1", design(param_hash="different")) is None
    assert json.loads((tmp_path / "approvals" / "run_1.json").read_text()) == record


def test_evidence_construction_and_html_escaping():
    data = evidence.build_evidence("run_1", summary(), design())
    assert data["request"] == "keep it < light"
    assert data["parameter_diff"] == [
        {"name": "span", "before": 3.0, "after": 4.0, "changed": True},
        {"name": "root", "before": 2.0, "after": None, "changed": True},
    ]
    rendered = evidence.render_html(data, "&lt;script&gt;bad()&lt;/script&gt;")
    assert "Requirement evaluation" in rendered and "Parameter diff" in rendered and "Limitations" in rendered
    assert "keep it &lt; light" in rendered and "PLA &amp; aluminum" in rendered
    assert "&lt;script&gt;bad()&lt;/script&gt;" in rendered
    assert "<script>bad()" not in rendered


def test_server_evidence_approval_and_report_routes(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend import server

    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))
    s = summary()
    d = design()
    monkeypatch.setattr(server, "_summary", lambda run_id: dict(s, champion=d))
    monkeypatch.setattr(server, "_find_design", lambda run_id, design_id: d)
    monkeypatch.setattr(server, "_events", lambda run_id: [])
    monkeypatch.setattr(server.RunSummary, "model_validate", lambda value: SimpleNamespace(
        champion=SimpleNamespace(model_dump=lambda mode="json": d)))
    client = TestClient(server.app)
    rid = "run_1"
    assert client.get(f"/api/runs/{rid}/approve").status_code == 404
    response = client.post(f"/api/runs/{rid}/approve", json={"design_id": "design_1", "approved_by": "Ada"})
    assert response.status_code == 200 and response.json()["approved_by"] == "Ada"
    assert client.get(f"/api/runs/{rid}/approve").json()["design_id"] == "design_1"
    assert client.get(f"/api/runs/{rid}/evidence").json()["design_id"] == "design_1"
    report = client.get(f"/api/runs/{rid}/report")
    assert report.status_code == 200 and "Requirement evaluation" in report.text
    assert "keep it &lt; light" in report.text

    monkeypatch.setattr(server, "_summary", lambda run_id: dict(s, champion=dict(d, design_id="other")))
    rejected = client.post(f"/api/runs/{rid}/approve", json={"design_id": "design_1"})
    assert rejected.status_code == 409


def test_commit_requires_approved_completed_champion(monkeypatch):
    """The CAD adapter is reachable only through an exact champion approval."""
    from fastapi.testclient import TestClient
    from backend import server

    champion = design()
    summary_data = summary(champion=champion, design_space_id="fin_v1")
    cad_calls = []
    approval_calls = []

    def commit_to_document(space, params):
        cad_calls.append((space, params))
        return SimpleNamespace(model_dump=lambda mode="json": {"geometry_key": "committed"})

    monkeypatch.setattr(server, "_summary", lambda run_id: summary_data)
    monkeypatch.setattr(server.W.cad, "commit_to_document", commit_to_document)

    approval = {"record": None}

    def load_approval(run_id, approved_design):
        approval_calls.append((run_id, approved_design))
        record = approval["record"]
        if record is None or (record.get("design_id"), record.get("param_hash")) != (
                approved_design.get("design_id"), approved_design.get("param_hash")):
            return None
        return record

    monkeypatch.setattr(server.evidence, "load_approval", load_approval)
    client = TestClient(server.app)
    route = "/api/runs/run_1/commit"

    # No approval record: the adapter must not be called.
    assert client.post(route, json={"design_id": champion["design_id"]}).status_code == 409
    assert cad_calls == []

    # A request for another design is rejected before approval/CAD lookups.
    assert client.post(route, json={"design_id": "not-the-champion"}).status_code == 409
    assert cad_calls == [] and len(approval_calls) == 1

    # A record bound to prior parameters is stale and cannot authorize this champion.
    approval["record"] = {"design_id": champion["design_id"], "param_hash": "old-parameters"}
    assert client.post(route, json={"design_id": champion["design_id"]}).status_code == 409
    assert cad_calls == [] and approval_calls[-1] == ("run_1", champion)

    approval["record"] = {"design_id": champion["design_id"], "param_hash": champion["param_hash"]}
    response = client.post(route, json={"design_id": champion["design_id"]})
    assert response.status_code == 200 and response.json()["geometry_key"] == "committed"
    assert len(cad_calls) == 1 and cad_calls[0][1] == champion["params"]

    summary_data["status"] = "running"
    assert client.post(route, json={"design_id": champion["design_id"]}).status_code == 409
    assert len(cad_calls) == 1

import json
import os
from pathlib import Path

os.environ.setdefault("FAKE_CAD_LATENCY", "0")
os.environ.setdefault("DARWIN_CACHE_DIR", str(Path(__file__).resolve().parent.parent.parent / ".darwin" / "test"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared import check  # noqa: E402
from shared.contracts import DesignResult  # noqa: E402
from shared.manifest import (  # noqa: E402
    ManifestUpdate, ProjectManifest, RevisionNote, manifest_hash,
)
from shared.mocks import fake_onboarding, fake_structural  # noqa: E402
from shared.mocks import make_fixtures_v2 as fx  # noqa: E402

V2 = Path(__file__).resolve().parent.parent / "fixtures" / "v2"


def test_v2_fixtures_pass_the_contract_check():
    assert check.check_v2() == []


def test_v1_design_result_still_validates_without_analysis():
    raw = json.loads((V2.parent / "design_result_example.json").read_text())
    assert "analysis" not in raw
    assert DesignResult.model_validate(raw).analysis is None


def test_manifest_hash_ignores_history_but_not_content():
    m = fx.manifest_bracket(3)
    h = manifest_hash(m)
    more = m.model_copy(update={"history": m.history + [RevisionNote(revision=9, at="x", by="y", change="z")]})
    assert manifest_hash(more) == h
    edited = m.model_copy(update={"name": "Another bracket"})
    assert manifest_hash(edited) != h


def test_check_rejects_url_in_doc_ref_and_unconfirmed_inputs_at_level_3():
    m = fx.manifest_bracket(3)
    bad = m.model_copy(update={"cad": m.cad.model_copy(update={"doc_ref": "https://cad.onshape.com/documents/x"})})
    assert any("env var NAMES" in p for p in check.check_manifest("bad", bad))
    lc = m.load_cases[0].model_copy(update={"confirmed": False})
    assert any("unconfirmed load case" in p for p in check.check_manifest("bad", m.model_copy(
        update={"load_cases": [lc]})))
    perm = m.model_copy(update={"authority": m.authority.model_copy(update={"permitted": ["write"]})})
    assert any("exceed maturity" in p for p in check.check_manifest("bad", perm))


def test_structural_mock_blocks_until_inputs_are_confirmed():
    draft = fx.manifest_bracket(1)
    assert {q.id for q in fake_structural.validate_manifest(draft)} == {"material", "load", "fixtures"}
    with pytest.raises(ValueError):
        fake_structural.evaluate(draft, {}, fx.BRACKET_GOAL)
    assert fake_structural.validate_manifest(fx.manifest_bracket(3)) == []


def test_sample_structural_run_has_a_failure_then_a_verified_repair():
    events = [json.loads(line) for line in (V2 / "sample_structural_run.jsonl").read_text().splitlines()]
    designs = [e["payload"]["design"] for e in events if e["type"] == "design_evaluated"]
    repair = next(d for d in designs if d["operator"] == "repair")
    failed = next(d for d in designs if d["design_id"] == repair["parent_ids"][0])
    assert not failed["score"]["feasible"] and repair["score"]["feasible"]
    assert repair["analysis"]["fidelity"] == "verification"
    assert any(e["type"] == "analysis_progress" for e in events)


def test_mock_server_onboarding_flow():
    from shared.mocks.mock_server import app
    fake_onboarding.reset()
    c = TestClient(app)
    ids = {p["project_id"]: p["maturity"] for p in c.get("/api/projects").json()}
    assert ids == {"fin_reference": 3, "bracket": 3}

    body = c.post("/api/projects/inspect", json={"doc_url": "https://example/bracket"}).json()
    pid, m = body["project_id"], ProjectManifest.model_validate(body["manifest"])
    assert m.authority.maturity == 1 and body["report"]["maturity"] == 1
    sem = [s.model_copy(update={"confirmed": True, "confidence": None}) for s in m.semantics]
    m2 = c.post("/api/projects/%s/manifest" % pid, json=ManifestUpdate(
        revision=1, by="test", semantics=sem).model_dump(mode="json")).json()
    assert m2["revision"] == 2
    stale = c.post("/api/projects/%s/manifest" % pid, json={"revision": 1, "by": "test"})
    assert stale.status_code == 409
    assert c.post("/api/projects/%s/activate" % pid).json()["maturity"] == 2
    answers = {q["field"]: "confirmed" for q in m2["open_questions"]}
    m3 = c.post("/api/projects/%s/manifest" % pid, json={"revision": 2, "by": "test", "answers": answers}).json()
    assert m3["open_questions"] == []
    probes = c.post("/api/projects/%s/probe" % pid).json()
    assert probes and probes[0]["case"] == "seed" and probes[0]["geometry"]["status"] == "ready"
    assert c.post("/api/projects/%s/activate" % pid).json()["maturity"] == 3

    duct = c.post("/api/discover", json={"doc_url": "https://example/duct"}).json()
    assert duct["report"]["maturity"] == 1 and duct["report"]["required_adapter"] == "cfd_*"


def test_mock_server_structural_run_and_commit_preview():
    from shared.mocks.mock_server import app
    fake_onboarding.reset()
    c = TestClient(app)
    run_id = "run_fixture_bracket"
    champ = c.get("/api/runs/%s" % run_id).json()["champion"]
    prev = c.get("/api/runs/%s/commit/preview" % run_id, params={"design_id": champ["design_id"]}).json()
    assert prev["maturity"] == 3 and prev["blocked_reason"]
    assert all("https" not in str(v) for v in prev.values())
    from shared.mocks.mock_server import RUNS
    started = c.post("/api/runs", json={"project_id": "bracket"}).json()["run_id"]
    try:
        assert started.startswith("run_")
    finally:
        c.post("/api/runs/%s/stop" % started)
        RUNS.pop(started, None)     # keep GET /api/runs as other tests expect it

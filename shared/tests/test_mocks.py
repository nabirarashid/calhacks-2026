import json
import os
from pathlib import Path

os.environ.setdefault("FAKE_CAD_LATENCY", "0")
os.environ.setdefault("FAKE_LLM_LATENCY", "0")

from fastapi.testclient import TestClient  # noqa: E402

from shared.contracts import DesignSpace, Goal  # noqa: E402
from shared.events import Event, validate_event  # noqa: E402
from shared.mocks import fake_cad, fake_llm, fake_sim  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SPACE = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
GOAL = Goal.model_validate_json((FIXTURES / "goal_example.json").read_text())


def test_fake_sim_catalog_and_aggregation():
    s = fake_sim.evaluate(SPACE, {}, GOAL)
    assert set(s.metrics) == {m.name for m in fake_sim.metric_catalog("fin_v1")}
    assert not s.feasible and s.aggregate < 0          # default fins are > 40 g total
    good = json.loads((FIXTURES / "design_result_example.json").read_text())["params"]
    g = fake_sim.evaluate(SPACE, good, GOAL)
    assert g.feasible and 0 <= g.aggregate <= 1
    ranks = fake_sim.pareto_ranks([s, g], GOAL)
    assert ranks[1] == 0 and ranks[0] > 0              # infeasible ranked after feasible


def test_fake_cad_cache_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))
    p = {"root_chord": 100.0, "semi_span": 55.0}
    before = fake_cad.budget_status().calls_ledger_total
    a = fake_cad.build_geometry(SPACE, p)
    b = fake_cad.build_geometry(SPACE, p)
    assert b.source == "cache" and b.onshape_calls == 0
    assert fake_cad.budget_status().calls_ledger_total == before + 1
    if a.status == "ready":
        assert fake_cad.geometry_file(a.geometry_key) is not None


def test_fake_llm_proposer_shape():
    block = {"n": 4, "params": [p.model_dump(mode="json") for p in SPACE.parameters], "top": []}
    ok = 0
    for i in range(10):
        r = fake_llm.call_model("proposer", "s%d" % i, "go\n```json\n%s\n```" % json.dumps(block))
        if isinstance(r.data.get("proposals"), list):
            assert len(r.data["proposals"]) == 4
            ok += 1
    assert ok >= 8


def test_mock_server_routes_and_ws():
    from shared.mocks.mock_server import app
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"]
    assert c.get("/api/design-spaces").json()[0]["source"]["doc_url"] is None
    assert len(c.get("/api/presets").json()) == 3
    assert c.post("/api/goal/parse", json={"text": "keep it under 30 g", "design_space_id": "fin_v1"}).status_code == 200
    runs = c.get("/api/runs").json()
    rid = runs[0]["run_id"]
    lines = c.get("/api/runs/%s/events" % rid).text.strip().splitlines()
    for line in lines:
        validate_event(Event.model_validate_json(line))
    with c.websocket_connect("/ws?run_id=%s" % rid) as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "run_started"
    champ = runs[0]["champion"]
    geo = champ["geometry"]
    if geo and geo["status"] == "ready":
        assert c.get(geo["stl_url"]).status_code == 200

"""Backend acceptance tests on all fakes (PLAN.md S3): no network, no cost."""
import json
import os
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_SIM", "fake")
    monkeypatch.setenv("DARWIN_CAD", "fake")
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FAKE_CAD_LATENCY", "0")
    monkeypatch.setenv("FAKE_LLM_LATENCY", "0")
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path / ".darwin"))
    monkeypatch.setenv("DARWIN_FIN_DOC_URL", "https://cad.onshape.com/documents/SECRETDOC/w/W/e/E")
    yield


def _run(config=None, until=60.0):
    from shared.contracts import Goal, RunConfig
    from backend.bus import Bus
    from backend.run_loop import RunController, new_run_id
    from backend.wiring import Wiring
    w = Wiring()
    bus = Bus()
    goal = Goal.model_validate_json((FIXTURES / "goal_example.json").read_text())
    ctl = RunController(w, bus.open(new_run_id()), w.spaces["fin_v1"], goal, RunConfig(**(config or {})))
    ctl.start()
    ctl.thread.join(until)
    assert not ctl.thread.is_alive(), "run did not finish"
    return ctl


def _types(ctl):
    return [e["type"] for e in ctl.ch.events]


def test_full_run_events_valid_and_ordered():
    from shared.events import Event, validate_event
    ctl = _run({"early_stop_patience": 99})
    evs = ctl.ch.events
    for e in evs:
        validate_event(Event.model_validate(e))
    t = _types(ctl)
    assert t[0] == "run_started" and t[-1] == "run_complete"
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    for needed in ("design_evaluated", "generation_complete", "champion_updated", "geometry_ready", "agent_message",
                   "baseline_progress", "landscape_ready", "budget_update"):
        assert needed in t, needed
    summary = evs[-1]["payload"]["summary"]
    assert summary["status"] == "complete"
    budget = ctl.config.budget()
    assert len(ctl.history.designs) == budget
    for m in ("cmaes", "random"):
        assert len(ctl.baseline_results[m]) == budget
        assert summary["curves"][m][-1]["evals"] == len(ctl.history.designs)   # matched budget
    assert summary["champion"]["score"]["aggregate"] == max(d.score.aggregate for d in ctl.history.designs)
    assert len({d.param_hash for d in ctl.history.designs}) == budget          # no duplicates evaluated


def test_generation_order_within_generation():
    ctl = _run({"generations": 3, "early_stop_patience": 99})
    t = _types(ctl)
    interleave = {"agent_message", "geometry_ready", "baseline_progress", "error", "landscape_ready"}
    for i, typ in enumerate(t):
        if typ == "generation_complete":
            nxt = [x for x in t[i + 1:] if x not in interleave]
            assert nxt and nxt[0] == "budget_update"
    first_gc = t.index("generation_complete")
    assert t.index("design_evaluated") < first_gc


def test_llm_cap_falls_back_to_ga():
    ctl = _run({"llm_max_calls": 0, "generations": 3, "early_stop_patience": 99})
    origins = {d.origin for d in ctl.history.designs}
    assert "fallback" in origins and "agent" not in origins
    summary = ctl.ch.events[-1]["payload"]["summary"]
    assert any(x.startswith("llm_fallback@") for x in summary["degradations"])
    assert any(e["type"] == "error" and e["payload"]["degraded_to"] == "fallback_proposer" for e in ctl.ch.events)


def test_baselines_matched_when_agent_stops_early():
    ctl = _run({"early_stop_patience": 1, "min_improvement": 10.0})     # every generation "stagnates"
    used = len(ctl.history.designs)
    assert used < ctl.config.budget()
    summary = ctl.ch.events[-1]["payload"]["summary"]
    for m in ("cmaes", "random"):
        assert summary["curves"][m][-1]["evals"] == used
        best = max(ctl.baseline_results[m][:used], key=lambda d: d.score.aggregate)
        assert summary["baseline_best"][m]["design_id"] == best.design_id


def test_geometry_build_cap():
    ctl = _run({"geometry_max_builds": 2, "early_stop_patience": 99})
    geo = [e for e in ctl.ch.events if e["type"] == "geometry_ready"]
    assert 1 <= len(geo) <= 3        # cap + the final champion


def test_recording_has_no_secrets_and_replays():
    from backend.bus import Bus
    from backend.replay import Replayer
    ctl = _run({"generations": 2, "early_stop_patience": 99})
    text = ctl.ch.path.read_text()
    assert "SECRETDOC" not in text and "cad.onshape.com" not in text
    bus = Bus()
    r = Replayer(bus, ctl.ch.path, "replay_test", speed=1000.0)
    ch = r.start()
    r.thread.join(30)
    assert [e["type"] for e in ch.events] == _types(ctl)
    assert all(e["run_id"] == "replay_test" for e in ch.events)


def test_goal_parser_mock_and_fallback(monkeypatch):
    from backend.agents import goal_parser
    from backend.wiring import Wiring
    w = Wiring()
    space = w.spaces["fin_v1"]
    g, res = goal_parser.parse_goal("Keep drag low and stay under 35 g", space, w.catalog("fin_v1"), w.presets)
    assert g.objectives and any(c.ref == "fin_mass_total_g" and c.value == 35 for c in g.constraints)
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "replay")      # empty cache -> unavailable -> preset fallback
    g2, res2 = goal_parser.parse_goal("flutter safe at 200 m/s, light", space, w.catalog("fin_v1"), w.presets)
    assert res2 is None and g2.parsed_by == "fallback"


def test_numeric_claim_check():
    from backend.agents.base import scrub_claims
    clean, bad = scrub_claims("Drag fell to 1.31 N and mass to 99.9 g with 3 fins", {"drag_n": 1.31, "fin_mass": 32.4})
    assert bad == ["99.9"] and "1.31" in clean and "[?]" in clean and "3 fins" in clean


def test_server_routes():
    from fastapi.testclient import TestClient
    import importlib
    import backend.server as server
    importlib.reload(server)
    c = TestClient(server.app)
    assert c.get("/api/health").json()["modes"]["llm"] == "mock"
    assert c.get("/api/design-spaces").json()[0]["source"]["doc_url"] is None
    goal = c.post("/api/goal/parse", json={"text": "minimize drag, under 40 g"}).json()
    rid = c.post("/api/runs", json={"goal": goal, "config": {"generations": 2}}).json()["run_id"]
    deadline = time.time() + 30
    while time.time() < deadline and c.get("/api/runs/%s" % rid).json()["status"] == "running":
        time.sleep(0.2)
    s = c.get("/api/runs/%s" % rid).json()
    assert s["status"] == "complete"
    with c.websocket_connect("/ws?run_id=%s" % rid) as ws:
        assert json.loads(ws.receive_text())["type"] == "run_started"
    champ = s["champion"]
    if champ["geometry"] and champ["geometry"]["status"] == "ready":
        assert c.get(champ["geometry"]["stl_url"]).status_code == 200
    assert c.post("/api/runs/%s/export" % rid, json={"design_id": champ["design_id"]}).status_code == 200
    assert "Darwin run" in c.get("/api/runs/%s/report" % rid).text
    rep = c.post("/api/replay", json={"recording": "sample_run.jsonl", "speed": 500}).json()["run_id"]
    assert rep.startswith("replay_")

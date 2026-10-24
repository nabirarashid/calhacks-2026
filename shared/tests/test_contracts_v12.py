import json
import os
from pathlib import Path

os.environ.setdefault("FAKE_CAD_LATENCY", "0")

from fastapi.testclient import TestClient  # noqa: E402

from shared.contracts import Goal  # noqa: E402
from shared.events import Event, validate_event  # noqa: E402
from shared.investigation import Notebook, Prediction, score_prediction  # noqa: E402
from shared.mocks import fake_wing  # noqa: E402

V2 = Path(__file__).resolve().parent.parent / "fixtures" / "v2"
ROOT = Path(__file__).resolve().parents[2]


def _events():
    return [json.loads(line) for line in (V2 / "sample_investigation.jsonl").read_text().splitlines()]


def test_prediction_scoring_is_deterministic():
    up = Prediction(metric="downforce_n", direction="up", pct_low=10, pct_high=20)
    assert score_prediction(up, 15.0).score == 1.0
    assert score_prediction(up, 35.0).score == 0.5           # right direction, wrong magnitude
    assert score_prediction(up, -8.0).score == 0.0
    flat = Prediction(metric="drag_n", direction="flat", pct_low=-2, pct_high=2)
    assert score_prediction(flat, 1.0).score == 1.0
    down = Prediction(metric="drag_n", direction="down", pct_low=-1, pct_high=-5)   # reversed bounds ok
    assert score_prediction(down, -3.0).in_range


def test_goal_editable_is_optional_and_old_goals_still_load():
    old = json.loads((V2.parent / "goal_example.json").read_text())
    assert Goal.model_validate(old).editable is None
    assert Goal.model_validate(dict(old, editable=["aoa_deg"])).editable == ["aoa_deg"]


def test_sample_investigation_tells_the_story_with_valid_events():
    events = _events()
    for e in events:
        validate_event(Event.model_validate(e))
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_complete"
    results = [e["payload"] for e in events if e["type"] == "step_result"]
    verdicts = [r["verdict"] for r in results]
    assert verdicts[0] == "rejected" and "accepted" in verdicts and verdicts[-1] == "pivot"
    plans = [e for e in events if e["type"] == "step_planned"]
    first_sim = next(i for i, e in enumerate(events) if e["type"] == "design_evaluated" and e["payload"]["design"]["generation"] == 1)
    assert events.index(plans[0]) < first_sim, "predictions are recorded before the simulation"
    nb = Notebook.model_validate([e for e in events if e["type"] == "notebook_updated"][-1]["payload"])
    assert len(nb.accuracy) == len(results) and nb.accuracy[-1] > nb.accuracy[0]
    assert nb.ruled_out
    versions = [e["payload"]["version"] for e in events if e["type"] == "design_applied" and e["payload"]["version"]]
    assert versions[0] == "Before Darwin" and versions[-1].startswith("Darwin:")
    final = events[-1]["payload"]["summary"]["champion"]["score"]["metrics"]
    assert final["drag_n"] <= 15.0


def test_editable_is_respected_in_the_sample():
    events = _events()
    goal = events[0]["payload"]["summary"]["goal"]
    seed = next(e["payload"]["design"] for e in events if e["type"] == "design_evaluated")
    for e in events:
        if e["type"] == "design_evaluated":
            d = e["payload"]["design"]["params"]
            changed = {k for k in d if d[k] != seed["params"][k]}
            assert changed <= set(goal["editable"])


def test_fake_wing_trends_match_the_principles():
    base = {p.name: p.default for p in fake_wing.WING_SPACE.parameters}
    m0 = fake_wing.wing_metrics(base)
    more_aoa = fake_wing.wing_metrics(dict(base, aoa_deg=10.0))
    wider = fake_wing.wing_metrics(dict(base, span_mm=1000.0))
    taller = fake_wing.wing_metrics(dict(base, endplate_height_mm=300.0))
    assert more_aoa["downforce_n"] > m0["downforce_n"] and more_aoa["l_over_d"] < m0["l_over_d"]
    assert wider["l_over_d"] > m0["l_over_d"] and taller["drag_induced_n"] < m0["drag_induced_n"]
    assert fake_wing.wing_metrics(dict(base, aoa_deg=16.0))["stall_margin_deg"] < 0


def test_mock_server_session_routes():
    from shared.mocks.mock_server import RUNS, app
    c = TestClient(app)
    insp = c.post("/api/inspect", json={"doc_url": "https://cad.onshape.com/documents/x/w/y/e/z"}).json()
    assert insp["project_id"] == "rear_wing" and {p["name"] for p in insp["params"]} >= {"aoa_deg", "span_mm"}
    s = c.post("/api/sessions", json={"doc_url": "x", "prompt": "more downforce"}).json()
    try:
        assert "chord_mm" in s["fixed"] and "aoa_deg" in s["editable"]
        assert c.get("/api/sessions/%s/notebook" % s["run_id"]).status_code == 200
    finally:
        c.post("/api/sessions/%s/stop" % s["run_id"])
        RUNS.pop(s["run_id"], None)
    done = c.get("/api/sessions/session_fixture_wing/notebook").json()
    assert done["accuracy"] and done["ruled_out"]


def test_wiring_loads_the_wing_project_with_the_fallback_solver(monkeypatch, tmp_path):
    monkeypatch.setenv("DARWIN_SIM", "real")
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path))
    from backend.wiring import Wiring
    w = Wiring()
    space = w.resolve("rear_wing")
    assert space.id == "rear_wing_v1" and w.packs["rear_wing"].pack_id == "aero"
    assert [m.name for m in w.catalog(space.scorer)][:2] == ["downforce_n", "drag_n"]

"""C4: the session API on a fresh router (mock LLM, mock CAD Variables, real wing solver)."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

URL = ("https://cad.onshape.com/documents/0123456789ab" +
       "cdef01234567/w/aaaaaaaaaaaa" +
       "aaaaaaaaaaaa/e/bbbbbbbbbbbb" +
       "bbbbbbbbbbbb")
PROMPT = "More downforce without going over 15 N of drag. You can change the angle and span. Keep the endplates."


@pytest.fixture
def client(tmp_path, monkeypatch):
    for k, v in {"DARWIN_SIM": "real", "DARWIN_CAD": "fake", "DARWIN_LLM_PROVIDER": "mock", "FAKE_LLM_LATENCY": "0",
                 "FAKE_CAD_LATENCY": "0", "DARWIN_CACHE_DIR": str(tmp_path / ".darwin"), "DARWIN_DOC_WING": URL}.items():
        monkeypatch.setenv(k, v)
    from shared.mocks import fake_cad
    fake_cad._VARIABLES.clear()
    fake_cad._VERSIONS.clear()
    from backend.bus import Bus
    from backend.sessions import make_router
    from backend.wiring import Wiring
    w, bus, runs = Wiring(), Bus(), {}
    app = FastAPI()
    app.include_router(make_router(w, bus, runs, lambda: any(r.thread.is_alive() for r in runs.values())))
    c = TestClient(app)
    c.state = {"runs": runs, "bus": bus, "fake_cad": fake_cad, "w": w}
    return c


def _wait(c, run_id, timeout=60):
    inv = c.state["runs"][run_id]
    inv.thread.join(timeout)
    assert not inv.thread.is_alive()
    return inv.ch.events


def test_inspect_matches_the_document_and_reads_live_values(client):
    r = client.post("/api/inspect", json={"doc_url": URL + "?configuration=default"}).json()
    assert r["project_id"] == "rear_wing" and r["source"] == "onshape"
    assert {p["name"] for p in r["params"]} >= {"aoa_deg", "span_mm", "endplate_height_mm"}
    other = "https://cad.onshape.com/documents/ffffffffffff" + "ffffffffffff/w/a/e/b"
    assert client.post("/api/inspect", json={"doc_url": other}).status_code == 404


def test_session_parses_runs_morphs_and_versions(client):
    fake = client.state["fake_cad"]
    fake.list_variables(URL)
    did = fake._doc_id(URL)
    fake._VARIABLES[did]["endplate_height_mm"] = 240.0          # the user's current design, not the defaults
    r = client.post("/api/sessions", json={"doc_url": URL, "prompt": PROMPT, "max_sims": 12, "max_steps": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["editable"] == ["aoa_deg", "span_mm"] and "endplate_height_mm" in body["fixed"]
    assert body["start_values_from"] == "onshape" and body["writes"] is True
    events = _wait(client, body["run_id"])
    seed = next(e["payload"]["design"] for e in events if e["type"] == "design_evaluated")
    assert seed["params"]["endplate_height_mm"] == 240.0        # started from Onshape, not from defaults
    applied = [e["payload"] for e in events if e["type"] == "design_applied"]
    versions = [a["version"] for a in applied if a["version"]]
    assert versions[0] == "Before Darwin" and versions[-1].startswith("Darwin:")
    assert fake._VERSIONS == versions
    accepted = [e for e in events if e["type"] == "step_result" and e["payload"]["verdict"] == "accepted"]
    morphs = [a for a in applied if not a["version"]]
    assert len(morphs) == len(accepted) and all(a["geometry"]["status"] == "ready" for a in morphs)
    final = events[-1]["payload"]["summary"]["champion"]["params"]
    live = fake._VARIABLES[did]
    assert live["aoa_deg"] == final["aoa_deg"] and live["span_mm"] == final["span_mm"]   # Onshape == champion
    assert live["endplate_height_mm"] == 240.0 and live["chord_mm"] == final["chord_mm"]  # untouched
    nb = client.get("/api/sessions/%s/notebook" % body["run_id"]).json()
    assert len(nb["accuracy"]) == len(accepted) + len([e for e in events if e["type"] == "step_result"
                                                       and e["payload"]["verdict"] != "accepted"])


def test_fin_session_writes_only_cad_driven_params(client, monkeypatch):
    fin_url = URL.replace("0123456789ab", "f1f1f1f1f1f1") + "?fin"
    monkeypatch.setenv("DARWIN_DOC_FIN", fin_url)
    fake = client.state["fake_cad"]
    sent = []
    real_apply = fake.apply_values
    monkeypatch.setattr(fake, "apply_values", lambda d, p, u: sent.append((dict(p), dict(u))) or real_apply(d, p, u))
    prompt = "Minimize drag. You can change the root chord, sweep, fin count and thickness."
    r = client.post("/api/sessions", json={"doc_url": fin_url, "prompt": prompt, "max_sims": 10, "max_steps": 4})
    assert r.status_code == 200, r.text
    assert r.json()["project_id"] == "fin_reference"
    _wait(client, r.json()["run_id"])
    assert sent and all("fin_count" not in p and "fin_count" not in u and "edge_profile" not in u for p, u in sent)


def test_one_session_at_a_time_and_stop(client):
    r1 = client.post("/api/sessions", json={"doc_url": URL, "prompt": PROMPT, "max_sims": 40, "max_steps": 12}).json()
    r2 = client.post("/api/sessions", json={"doc_url": URL, "prompt": PROMPT})
    assert r2.status_code == 409
    assert client.post("/api/sessions/%s/stop" % r1["run_id"]).json()["stopping"]
    events = _wait(client, r1["run_id"])
    assert events[-1]["payload"]["summary"]["status"] in ("stopped", "complete")
    assert client.post("/api/sessions/nope/stop").status_code == 404


def test_bad_requests(client):
    assert client.post("/api/sessions", json={"doc_url": URL, "prompt": "  "}).status_code == 422
    assert client.post("/api/sessions", json={"doc_url": "https://example.com", "prompt": "x"}).status_code == 404


def test_session_refuses_to_write_when_onshape_cannot_be_read(client, monkeypatch):
    fake = client.state["fake_cad"]

    def down(url):
        raise RuntimeError("HTTP 429")
    monkeypatch.setattr(fake, "list_variables", down)
    r = client.post("/api/sessions", json={"doc_url": URL, "prompt": PROMPT})
    assert r.status_code == 503 and "Onshape" in r.json()["detail"]
    assert client.post("/api/inspect", json={"doc_url": URL}).json()["source"] == "unreadable"


def test_locked_params_never_change(client, monkeypatch):
    monkeypatch.setenv("DARWIN_LOCKED_PARAMS", "chord_mm")
    r = client.post("/api/sessions", json={"doc_url": URL, "max_sims": 8, "max_steps": 3,
                                           "prompt": "More downforce under 15 N of drag. You can change the chord and span."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["editable"] == ["span_mm"] and "chord_mm" in body["fixed"]
    events = _wait(client, body["run_id"])
    assert all(e["payload"]["design"]["params"]["chord_mm"] == 280.0 for e in events if e["type"] == "design_evaluated")
    r = client.post("/api/sessions", json={"doc_url": URL, "prompt": "Cut drag. Only change the chord."})
    assert r.status_code == 422 and "locked" in r.json()["detail"]


def test_offline_panel_default_names_the_wing(client):
    r = client.post("/api/inspect", json={"doc_url": "mock://rear-wing"})       # client runs with DARWIN_CAD=fake
    assert r.status_code == 200 and r.json()["project_id"] == "rear_wing"
    assert client.post("/api/inspect", json={"doc_url": "mock://nope"}).status_code == 404


def test_replay_mode_run_plays_the_recording_not_a_new_session(client, monkeypatch):
    from backend import replay
    monkeypatch.setitem(client.state["w"].modes, "mode", "replay")
    r = client.post("/api/sessions", json={"doc_url": URL, "prompt": "anything at all"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"].startswith("replay_") and body["writes"] is False
    assert body["replay_of"] == "session_1925_d20d.jsonl" and "chord_mm" in body["fixed"]
    rep = client.state["runs"][body["run_id"]]
    assert isinstance(rep, replay.Replayer)
    assert client.post("/api/sessions/%s/stop" % body["run_id"]).status_code == 200


def test_geometry_check_locks_a_parameter_the_cad_ignores(client, monkeypatch):
    fake = client.state["fake_cad"]
    real_measure = fake.measure_parts

    def chord_ignored(doc_url, roles=None, bbox_mm=None):           # the Sat 19:30 wing: chord drives nothing
        m = real_measure(doc_url, roles, bbox_mm)
        did = fake._doc_id(doc_url)
        saved = fake._VARIABLES[did]["chord_mm"]
        fake._VARIABLES[did]["chord_mm"] = 280.0
        try:
            return real_measure(doc_url, roles, bbox_mm)
        finally:
            fake._VARIABLES[did]["chord_mm"] = saved
    monkeypatch.setattr(fake, "measure_parts", chord_ignored)
    r = client.post("/api/sessions", json={"doc_url": URL, "max_sims": 10, "max_steps": 5,
                                           "prompt": "Cut drag. You can only change the chord."})
    assert r.status_code == 200, r.text
    events = _wait(client, r.json()["run_id"])
    msgs = [e["payload"]["message"]["summary"] for e in events if e["type"] == "agent_message"]
    assert any(m.startswith("Locked chord_mm") for m in msgs), msgs
    writes = [e for e in events if e["type"] == "design_applied" and not e["payload"]["version"]]
    assert len(writes) == 1                                          # nothing after the lock


def test_geometry_check_passes_on_a_consistent_wing(client):
    r = client.post("/api/sessions", json={"doc_url": URL, "prompt": PROMPT, "max_sims": 10, "max_steps": 4})
    events = _wait(client, r.json()["run_id"])
    msgs = [e["payload"]["message"]["summary"] for e in events if e["type"] == "agent_message"]
    writes = [e for e in events if e["type"] == "design_applied" and not e["payload"]["version"]]
    if writes:
        assert "CAD check: Onshape's geometry matches the solver's inputs." in msgs
    assert not any(m.startswith("Locked") or m.startswith("CAD check: Onshape's wing") for m in msgs)

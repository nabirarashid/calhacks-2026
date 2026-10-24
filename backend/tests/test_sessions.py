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
    c.state = {"runs": runs, "bus": bus, "fake_cad": fake_cad}
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

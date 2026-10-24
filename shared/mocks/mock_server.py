"""Fixture-backed Darwin API on :8000 (PLAN.md B.8 / B.10). Run: python -m shared.mocks.mock_server

Implements every REST route in B.8, plus the contracts-v2 project routes (PLAN.md v3 B.7)
backed by shared.mocks.fake_onboarding. POST /api/runs and POST /api/replay stream
fixtures/sample_run.jsonl over /ws at its recorded timing (x speed), with run_id
rewritten; a run for a bracket project streams fixtures/v2/sample_structural_run.jsonl. The goal you submit is shown in the summaries; the designs are
always the recorded ones. Geometry comes from fixtures/geometry/. Env:
PORT (8000), MOCK_SPEED (1.0).
"""
import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from shared.contracts import CONTRACT_VERSION, DesignSpace, Goal, MetricInfo
from shared.manifest import InspectRequest, ManifestUpdate
from shared.mocks import fake_cad, fake_llm, fake_onboarding

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample_run.jsonl"
TEMPLATE = [json.loads(line) for line in SAMPLE.read_text().splitlines() if line.strip()]
TEMPLATE_RUN_ID = TEMPLATE[0]["run_id"]
SPACE = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
CATALOG = json.loads((FIXTURES / "metric_catalog_fin.json").read_text())
PRESETS = json.loads((FIXTURES / "presets.json").read_text())
GOAL_EXAMPLE = json.loads((FIXTURES / "goal_example.json").read_text())
STRUCTURAL = [json.loads(line) for line in (FIXTURES / "v2" / "sample_structural_run.jsonl").read_text().splitlines()
              if line.strip()]
INVESTIGATION = [json.loads(line) for line in (FIXTURES / "v2" / "sample_investigation.jsonl").read_text().splitlines()
                 if line.strip()]


class Run:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events = []  # type: List[Dict[str, Any]]
        self.subscribers = set()  # type: Set[asyncio.Queue]
        self.task = None  # type: Optional[asyncio.Task]
        self.status = "running"

    def summary(self) -> Optional[Dict[str, Any]]:
        for ev in reversed(self.events):
            if ev["type"] in ("run_complete", "run_started"):
                s = dict(ev["payload"]["summary"])
                if self.status == "stopped":
                    s["status"] = "stopped"
                return s
        return None


RUNS = {}  # type: Dict[str, Run]
WILDCARD = set()  # type: Set[asyncio.Queue]


def _remap(ev: Dict[str, Any], run_id: str, goal: Optional[Dict[str, Any]], ts: float) -> Dict[str, Any]:
    out = json.loads(json.dumps(ev).replace(ev["run_id"], run_id))
    out["ts"] = round(ts, 3)
    summary = out["payload"].get("summary")
    if goal is not None and isinstance(summary, dict):
        summary["goal"] = goal
    return out


async def _publish(run: Run, ev: Dict[str, Any]) -> None:
    run.events.append(ev)
    for q in list(run.subscribers) + list(WILDCARD):
        q.put_nowait(ev)


async def _stream(run: Run, goal: Optional[Dict[str, Any]], speed: float, template: List[Dict[str, Any]]) -> None:
    t_start = time.time()
    t0 = template[0]["ts"]
    try:
        for ev in template:
            delay = (ev["ts"] - t0) / max(speed, 0.01) - (time.time() - t_start)
            if delay > 0:
                await asyncio.sleep(delay)
            await _publish(run, _remap(ev, run.run_id, goal, time.time()))
        run.status = "complete"
    except asyncio.CancelledError:
        run.status = "stopped"
        raise


def _start(prefix: str, goal: Optional[Dict[str, Any]], speed: float,
           template: Optional[List[Dict[str, Any]]] = None) -> Run:
    run_id = "%s_%s_%s" % (prefix, time.strftime("%H%M"), uuid.uuid4().hex[:4])
    run = Run(run_id)
    RUNS[run_id] = run
    run.task = asyncio.get_event_loop().create_task(_stream(run, goal, speed, template or TEMPLATE))
    return run


def _preload_sample() -> None:
    for template in (STRUCTURAL, INVESTIGATION, TEMPLATE):    # the fin sample stays first in GET /api/runs
        run = Run(template[0]["run_id"])
        run.events = list(template)
        run.status = "complete"
        RUNS[run.run_id] = run


def _find_design(run_id: str, design_id: str) -> Dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    for ev in run.events:
        d = ev["payload"].get("design") or ev["payload"].get("best")
        if isinstance(d, dict) and d.get("design_id") == design_id:
            return d
        s = ev["payload"].get("summary")
        if isinstance(s, dict) and s.get("champion") and s["champion"]["design_id"] == design_id:
            return s["champion"]
    raise HTTPException(404, "unknown design")


app = FastAPI(title="Darwin mock API", version=CONTRACT_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_preload_sample()


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "contract": CONTRACT_VERSION,
            "modes": {"sim": "fake", "cad": "fake", "llm": "mock", "mode": "mock_server"}}


@app.get("/api/design-spaces")
def design_spaces() -> List[Dict[str, Any]]:
    d = SPACE.model_dump(mode="json")
    d["source"]["doc_url"] = None
    return [d]


@app.get("/api/metrics")
def metrics(scorer: str = "fin_v1") -> List[Dict[str, Any]]:
    if scorer != "fin_v1":
        raise HTTPException(404, "unknown scorer")
    return CATALOG


@app.get("/api/presets")
def presets() -> List[Dict[str, Any]]:
    return PRESETS


@app.post("/api/goal/parse")
def parse_goal(body: Dict[str, Any]) -> Dict[str, Any]:
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(422, "text is required")
    block = json.dumps({"text": text, "metrics": [m["name"] for m in CATALOG]})
    res = fake_llm.call_model("goal_parser", "mock", "Parse.\n```json\n%s\n```" % block)
    try:
        return Goal.model_validate(res.data).model_dump(mode="json")
    except Exception:  # noqa: BLE001 — mock's malformed 5 %: fall back like the real backend
        g = dict(GOAL_EXAMPLE, source_text=text, parsed_by="fallback")
        return g


@app.post("/api/runs")
async def start_run(body: Dict[str, Any], speed: Optional[float] = None) -> Dict[str, str]:
    goal = body.get("goal")
    if goal is not None:
        goal = Goal.model_validate(goal).model_dump(mode="json")
    project = str(body.get("project_id") or body.get("design_space_id") or "")
    template = STRUCTURAL if project.startswith("bracket") else TEMPLATE
    run = _start("run", goal, speed or float(os.environ.get("MOCK_SPEED", "1.0")), template)
    return {"run_id": run.run_id}


@app.get("/api/runs")
def list_runs() -> List[Dict[str, Any]]:
    out = [r.summary() for r in RUNS.values()]
    return [s for s in reversed(out) if s is not None]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None or run.summary() is None:
        raise HTTPException(404, "unknown run")
    return run.summary()  # type: ignore[return-value]


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> Dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    if run.task is not None and not run.task.done():
        run.task.cancel()
    run.status = "stopped" if run.status == "running" else run.status
    return run.summary() or {}


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> PlainTextResponse:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown run")
    return PlainTextResponse("\n".join(json.dumps(e) for e in run.events) + "\n", media_type="application/x-ndjson")


@app.post("/api/replay")
async def replay(body: Dict[str, Any]) -> Dict[str, str]:
    if body.get("recording", "sample_run.jsonl") != "sample_run.jsonl":
        raise HTTPException(404, "mock server only has sample_run.jsonl")
    run = _start("replay", None, float(body.get("speed", 1.0)))
    return {"run_id": run.run_id}


@app.get("/api/geometry/{name}")
def geometry(name: str) -> FileResponse:
    key = name[:-4] if name.endswith(".stl") else name
    path = fake_cad.geometry_file(key)
    if path is None:
        raise HTTPException(404, "geometry not cached")
    return FileResponse(str(path), media_type="model/stl")


@app.post("/api/runs/{run_id}/commit")
def commit(run_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    d = _find_design(run_id, str(body.get("design_id")))
    return fake_cad.commit_to_document(SPACE, d["params"]).model_dump(mode="json")


@app.post("/api/runs/{run_id}/export")
def export(run_id: str, body: Dict[str, Any]) -> FileResponse:
    d = _find_design(run_id, str(body.get("design_id")))
    z = fake_cad.export_print_package(SPACE, d["params"], Path(".darwin") / "exports")
    return FileResponse(str(z), media_type="application/zip", filename=z.name)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str) -> HTMLResponse:
    s = get_run(run_id)
    champ = s.get("champion") or {}
    rows = "".join("<tr><td>%s</td><td>%.3f</td></tr>" % (k, v)
                   for k, v in (champ.get("score", {}).get("metrics", {}) or {}).items())
    return HTMLResponse("<html><body><h1>Darwin report (mock)</h1><p>%s</p><h2>Champion %s</h2>"
                        "<table>%s</table></body></html>" % (s["goal"]["source_text"], champ.get("design_id", "-"), rows))


@app.get("/api/budget")
def budget() -> Dict[str, Any]:
    for run in reversed(list(RUNS.values())):
        for ev in reversed(run.events):
            if ev["type"] == "budget_update":
                return ev["payload"]["budget"]
    return json.loads((FIXTURES / "budget_example.json").read_text())


# ---------------------------------------------------------------- v1.2: sessions (PLAN.md B.6)

def _session_project(doc_url: str) -> str:
    return "fin_reference" if "fin" in doc_url.lower() else "rear_wing"


@app.post("/api/inspect")
def inspect_doc(body: Dict[str, Any]) -> Dict[str, Any]:
    pid = _session_project(str(body.get("doc_url", "")))
    space = fake_onboarding.get(pid).design_space if fake_onboarding.get(pid) else None
    if space is None:
        raise HTTPException(404, "Darwin supports the rear wing and fin projects")
    return {"project_id": pid, "fixed": [],
            "params": [{"name": q.name, "unit": q.unit, "value": q.default, "min": q.min, "max": q.max}
                       for q in space.parameters]}


@app.post("/api/sessions")
async def start_session(body: Dict[str, Any], speed: Optional[float] = None) -> Dict[str, Any]:
    """Streams the recorded sample investigation, whatever the prompt (it's a mock)."""
    goal = INVESTIGATION[0]["payload"]["summary"]["goal"]
    run = _start("session", None, speed or float(os.environ.get("MOCK_SPEED", "1.0")), INVESTIGATION)
    params = [q["name"] for q in INVESTIGATION[0]["payload"]["design_space"]["parameters"]]
    editable = goal.get("editable") or params
    return {"run_id": run.run_id, "project_id": "rear_wing", "goal": goal, "editable": editable,
            "fixed": [p for p in params if p not in editable]}


@app.get("/api/sessions/{run_id}/notebook")
def session_notebook(run_id: str) -> Dict[str, Any]:
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(404, "unknown session")
    for ev in reversed(run.events):
        if ev["type"] == "notebook_updated":
            return ev["payload"]
    return {"beliefs": [], "lever_effects": {}, "ruled_out": [], "accuracy": []}


@app.post("/api/sessions/{run_id}/stop")
def stop_session(run_id: str) -> Dict[str, Any]:
    return stop_run(run_id)


# ---------------------------------------------------------------- contracts v2: projects (PLAN.md v3 B.7)

def _project(project_id: str):
    m = fake_onboarding.get(project_id)
    if m is None:
        raise HTTPException(404, "unknown project")
    return m


@app.get("/api/projects")
def projects() -> List[Dict[str, Any]]:
    return [p.model_dump(mode="json") for p in fake_onboarding.summaries()]


@app.post("/api/projects/inspect")
def inspect(body: InspectRequest) -> Dict[str, Any]:
    return fake_onboarding.inspect(body.doc_url).model_dump(mode="json")


@app.post("/api/discover")
def discover(body: Dict[str, Any]) -> Dict[str, Any]:
    """Alias for /api/projects/inspect (v2). The v1 DesignSpace body is retired."""
    return fake_onboarding.inspect(str(body.get("doc_url", ""))).model_dump(mode="json")


@app.get("/api/projects/{project_id}/manifest")
def get_manifest(project_id: str) -> Dict[str, Any]:
    return _project(project_id).model_dump(mode="json")


@app.post("/api/projects/{project_id}/manifest")
def update_manifest(project_id: str, body: ManifestUpdate) -> Dict[str, Any]:
    _project(project_id)
    try:
        return fake_onboarding.update(project_id, body).model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/projects/{project_id}/probe")
def probe(project_id: str) -> List[Dict[str, Any]]:
    m = _project(project_id)
    cases = [{p.name: p.default for p in m.design_space.parameters}]
    for p in m.design_space.parameters:
        if p.kind != "choice" and p.min is not None and p.max is not None and len(cases) < 9:
            cases += [{p.name: p.min}, {p.name: p.max}]
    return [r.model_dump(mode="json") for r in fake_cad.probe(m, cases[:9])]


@app.post("/api/projects/{project_id}/activate")
def activate(project_id: str) -> Dict[str, Any]:
    _project(project_id)
    return fake_onboarding.activate(project_id).model_dump(mode="json")


@app.get("/api/runs/{run_id}/commit/preview")
def commit_preview(run_id: str, design_id: str) -> Dict[str, Any]:
    d = _find_design(run_id, design_id)
    project = "bracket" if d["design_id"].startswith("run_fixture_bracket") or "flange_length" in d["params"] \
        else "fin_reference"
    return fake_cad.preview_commit(_project(project), d["params"]).model_dump(mode="json")


@app.websocket("/ws")
async def ws(websocket: WebSocket, run_id: str = Query("*")) -> None:
    await websocket.accept()
    q = asyncio.Queue()  # type: asyncio.Queue
    if run_id == "*":
        backlog = [e for r in RUNS.values() for e in r.events]
        WILDCARD.add(q)
        target = None
    else:
        target = RUNS.get(run_id)
        if target is None:
            await websocket.close(code=4404)
            return
        backlog = list(target.events)
        target.subscribers.add(q)
    try:
        for ev in backlog:
            await websocket.send_text(json.dumps(ev))
        while True:
            ev = await q.get()
            await websocket.send_text(json.dumps(ev))
    except WebSocketDisconnect:
        pass
    finally:
        WILDCARD.discard(q)
        if target is not None:
            target.subscribers.discard(q)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="info")

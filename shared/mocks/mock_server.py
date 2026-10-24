"""Fixture-backed Darwin API on :8000 (PLAN.md B.8 / B.10). Run: python -m shared.mocks.mock_server

Implements every REST route in B.8. POST /api/runs and POST /api/replay stream
fixtures/sample_run.jsonl over /ws at its recorded timing (x speed), with run_id
rewritten. The goal you submit is shown in the summaries; the designs are
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
from shared.mocks import fake_cad, fake_llm

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SAMPLE = FIXTURES / "sample_run.jsonl"
TEMPLATE = [json.loads(line) for line in SAMPLE.read_text().splitlines() if line.strip()]
TEMPLATE_RUN_ID = TEMPLATE[0]["run_id"]
SPACE = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
CATALOG = json.loads((FIXTURES / "metric_catalog_fin.json").read_text())
PRESETS = json.loads((FIXTURES / "presets.json").read_text())
GOAL_EXAMPLE = json.loads((FIXTURES / "goal_example.json").read_text())


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
    out = json.loads(json.dumps(ev).replace(TEMPLATE_RUN_ID, run_id))
    out["ts"] = round(ts, 3)
    summary = out["payload"].get("summary")
    if goal is not None and isinstance(summary, dict):
        summary["goal"] = goal
    return out


async def _publish(run: Run, ev: Dict[str, Any]) -> None:
    run.events.append(ev)
    for q in list(run.subscribers) + list(WILDCARD):
        q.put_nowait(ev)


async def _stream(run: Run, goal: Optional[Dict[str, Any]], speed: float) -> None:
    t_start = time.time()
    t0 = TEMPLATE[0]["ts"]
    try:
        for ev in TEMPLATE:
            delay = (ev["ts"] - t0) / max(speed, 0.01) - (time.time() - t_start)
            if delay > 0:
                await asyncio.sleep(delay)
            await _publish(run, _remap(ev, run.run_id, goal, time.time()))
        run.status = "complete"
    except asyncio.CancelledError:
        run.status = "stopped"
        raise


def _start(prefix: str, goal: Optional[Dict[str, Any]], speed: float) -> Run:
    run_id = "%s_%s_%s" % (prefix, time.strftime("%H%M"), uuid.uuid4().hex[:4])
    run = Run(run_id)
    RUNS[run_id] = run
    run.task = asyncio.get_event_loop().create_task(_stream(run, goal, speed))
    return run


def _preload_sample() -> None:
    run = Run(TEMPLATE_RUN_ID)
    run.events = list(TEMPLATE)
    run.status = "complete"
    RUNS[TEMPLATE_RUN_ID] = run


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
    run = _start("run", goal, speed or float(os.environ.get("MOCK_SPEED", "1.0")))
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


@app.post("/api/discover")
def discover(body: Dict[str, Any]) -> Dict[str, Any]:
    return fake_cad.discover_design_space(str(body.get("doc_url", "")),
                                          probe=bool(body.get("probe"))).model_dump(mode="json")


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

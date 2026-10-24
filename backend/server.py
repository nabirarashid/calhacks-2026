"""Darwin backend: REST + websocket (PLAN.md B.8). Run from the repo root: python -m backend.server"""
import asyncio
import html
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from shared.contracts import (
    CONTRACT_VERSION, BudgetStatus, DesignSpace, Goal, ModelBudget, RunConfig, RunSummary,
)

from backend import llm, replay
from backend.agents import goal_parser
from backend.bus import Bus, runs_dir
from backend.run_loop import RunController, new_run_id
from backend.wiring import ROOT, Wiring

logging.basicConfig(level=os.environ.get("DARWIN_LOG", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("darwin.server")

W = Wiring()
BUS = Bus()
RUNS = {}  # type: Dict[str, Any]       # run_id -> RunController | Replayer
GEOMETRY_DIRS = [ROOT / "demo" / "geometry", ROOT / "shared" / "fixtures" / "geometry"]

app = FastAPI(title="Darwin backend", version=CONTRACT_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
log.info("modes: %s", W.modes)


class ParseGoalRequest(BaseModel):
    text: str
    design_space_id: str = "fin_v1"


class StartRunRequest(BaseModel):
    goal: Goal
    design_space_id: str = "fin_v1"
    config: Dict[str, Any] = {}


class ReplayRequest(BaseModel):
    recording: str = "sample_run.jsonl"
    speed: float = 1.0


class DesignRequest(BaseModel):
    design_id: str


class DiscoverRequest(BaseModel):
    doc_url: str
    probe: bool = False


def _space(space_id: str) -> DesignSpace:
    if space_id not in W.spaces:
        raise HTTPException(404, "unknown design space %r" % space_id)
    return W.spaces[space_id]


def _events(run_id: str) -> List[Dict[str, Any]]:
    ch = BUS.get(run_id)
    if ch is not None:
        return list(ch.events)
    path = replay.find_recording("%s.jsonl" % run_id)
    if path is None:
        raise HTTPException(404, "unknown run %r" % run_id)
    return replay.load(path)


def _summary(run_id: str) -> Dict[str, Any]:
    s = replay.last_summary(_events(run_id))
    if s is None:
        raise HTTPException(404, "run %r has no summary yet" % run_id)
    return s


def _find_design(run_id: str, design_id: str) -> Dict[str, Any]:
    for ev in reversed(_events(run_id)):
        p = ev["payload"]
        for d in (p.get("design"), p.get("best"), (p.get("summary") or {}).get("champion")):
            if isinstance(d, dict) and d.get("design_id") == design_id:
                return d
    raise HTTPException(404, "unknown design %r" % design_id)


# ------------------------------------------------------------------ REST

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "contract": CONTRACT_VERSION, "modes": {k: W.modes.get(k, "?") for k in ("sim", "cad", "llm", "mode")}}


@app.get("/api/design-spaces")
def design_spaces() -> List[Dict[str, Any]]:
    return [W.public_space(s).model_dump(mode="json") for s in W.spaces.values()]


@app.get("/api/metrics")
def metrics(scorer: str = "fin_v1") -> List[Dict[str, Any]]:
    try:
        return [m.model_dump(mode="json") for m in W.catalog(scorer)]
    except KeyError:
        raise HTTPException(404, "unknown scorer %r" % scorer)


@app.get("/api/presets")
def presets() -> List[Dict[str, Any]]:
    return [p.model_dump(mode="json") for p in W.presets]


@app.post("/api/goal/parse")
def parse_goal(req: ParseGoalRequest) -> Dict[str, Any]:
    text = req.text.strip()
    if not text:
        raise HTTPException(422, "text is required")
    if len(text) > 1000:
        raise HTTPException(422, "goal text is limited to 1000 characters")
    space = _space(req.design_space_id)
    goal, _ = goal_parser.parse_goal(text, space, W.catalog(space.scorer), W.presets)
    return goal.model_dump(mode="json")


@app.post("/api/runs")
def start_run(req: StartRunRequest) -> Dict[str, str]:
    space = _space(req.design_space_id)
    try:
        config = RunConfig.model_validate(req.config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, "invalid config: %s" % e)
    catalog = {m.name for m in W.catalog(space.scorer)}
    bad = [o.metric for o in req.goal.objectives if o.metric not in catalog]
    if bad or not req.goal.objectives:
        raise HTTPException(422, "goal objectives must use catalog metrics; bad: %s" % bad)
    if any(r is not None and r.status == "running" for r in _active()):
        raise HTTPException(409, "a run is already in progress; stop it first")
    run_id = new_run_id()
    ctl = RunController(W, BUS.open(run_id), space, req.goal, config)
    RUNS[run_id] = ctl
    ctl.start()
    return {"run_id": run_id}


def _active() -> List[Any]:
    return [getattr(r, "summary", None) for r in RUNS.values() if isinstance(r, RunController) and r.thread.is_alive()]


@app.get("/api/runs")
def list_runs() -> List[Dict[str, Any]]:
    seen, out = set(), []
    for run_id in reversed(list(BUS.channels)):
        s = replay.last_summary(BUS.channels[run_id].events)
        if s:
            out.append(s)
            seen.add(run_id)
    for path in reversed(replay.list_recordings()):
        run_id = path.stem
        if run_id in seen:
            continue
        try:
            first = path.open().readline()
            ev = json.loads(first)
            s = replay.last_summary(replay.load(path))
        except (OSError, ValueError, KeyError):
            continue
        if s:
            s = dict(s, recording=path.name)
            out.append(s)
            seen.add(run_id)
            seen.add(ev.get("run_id"))
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> Dict[str, Any]:
    return _summary(run_id)


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> Dict[str, Any]:
    r = RUNS.get(run_id)
    if r is None:
        raise HTTPException(404, "unknown or finished run %r" % run_id)
    r.stop()
    return _summary(run_id)


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> PlainTextResponse:
    return PlainTextResponse("\n".join(json.dumps(e) for e in _events(run_id)) + "\n", media_type="application/x-ndjson")


@app.post("/api/replay")
def start_replay(req: ReplayRequest) -> Dict[str, str]:
    path = replay.find_recording(req.recording)
    if path is None:
        raise HTTPException(404, "recording %r not found" % req.recording)
    run_id = new_run_id("replay")
    r = replay.Replayer(BUS, path, run_id, req.speed)
    RUNS[run_id] = r
    r.start()
    return {"run_id": run_id}


@app.get("/api/geometry/{name}")
def geometry(name: str) -> FileResponse:
    key = name[:-4] if name.endswith(".stl") else name
    if not key.isalnum():
        raise HTTPException(400, "bad geometry key")
    path = None  # type: Optional[Path]
    try:
        path = W.cad.geometry_file(key)
    except Exception as e:  # noqa: BLE001
        log.warning("cad.geometry_file failed: %s", e)
    for d in GEOMETRY_DIRS:
        if path is None and (d / ("%s.stl" % key)).exists():
            path = d / ("%s.stl" % key)
    if path is None:
        raise HTTPException(404, "geometry %s not cached" % key)
    return FileResponse(str(path), media_type="model/stl")


@app.post("/api/runs/{run_id}/commit")
def commit(run_id: str, req: DesignRequest) -> Dict[str, Any]:
    d = _find_design(run_id, req.design_id)
    space = _space(_summary(run_id)["design_space_id"])
    return W.cad.commit_to_document(space, d["params"]).model_dump(mode="json")


@app.post("/api/runs/{run_id}/export")
def export(run_id: str, req: DesignRequest) -> FileResponse:
    d = _find_design(run_id, req.design_id)
    space = _space(_summary(run_id)["design_space_id"])
    try:
        z = W.cad.export_print_package(space, d["params"], runs_dir().parent / "exports")
    except NotImplementedError as e:
        raise HTTPException(501, "print export not available yet: %s" % e)
    if not z:
        raise HTTPException(502, "print export failed")
    return FileResponse(str(z), media_type="application/zip", filename=Path(z).name)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str) -> HTMLResponse:
    """Tier 1 placeholder report; the full engineering report lands in Tier 3 (backend/report.py)."""
    s = RunSummary.model_validate(_summary(run_id))
    narrative = ""
    for ev in reversed(_events(run_id)):
        m = ev["payload"].get("message") if ev["type"] == "agent_message" else None
        if m and m["agent"] == "reporter":
            narrative = "<h2>%s</h2><p>%s</p>" % (html.escape(m["summary"]), html.escape(m["body"]).replace("\n", "<br>"))
            break
    rows = ""
    if s.champion and s.seed_design:
        for k, v in s.champion.score.metrics.items():
            rows += "<tr><td>%s</td><td>%.3f</td><td>%.3f</td></tr>" % (html.escape(k), s.seed_design.score.metrics.get(k, 0), v)
    return HTMLResponse("<!doctype html><meta charset=utf-8><title>Darwin report %s</title>"
                        "<body style='font-family:system-ui;max-width:860px;margin:2rem auto'>"
                        "<h1>Darwin run %s</h1><p><b>Goal:</b> %s</p>%s"
                        "<table border=1 cellpadding=4><tr><th>metric</th><th>seed</th><th>champion</th></tr>%s</table>"
                        % (s.run_id, s.run_id, html.escape(s.goal.source_text), narrative, rows))


@app.get("/api/budget")
def budget() -> Dict[str, Any]:
    for r in reversed(list(RUNS.values())):
        if isinstance(r, RunController):
            return r.budget_status().model_dump(mode="json")
    return BudgetStatus(onshape=W.cad.budget_status(),
                        model=ModelBudget(provider=llm.provider_name(), calls_run=0, calls_cap_run=0, spend_run_usd=0.0,
                                          spend_cap_run_usd=float(os.environ.get("DARWIN_SPEND_CAP_RUN_USD", "0.30")),
                                          spend_total_usd=llm.SpendLedger.read()["total_usd"],
                                          spend_cap_total_usd=llm.SpendLedger.cap()),
                        evals_used=0, evals_budget=0).model_dump(mode="json")


@app.post("/api/discover")
def discover(req: DiscoverRequest) -> Dict[str, Any]:
    try:
        space = W.cad.discover_design_space(req.doc_url, probe=req.probe)
    except NotImplementedError as e:
        raise HTTPException(501, "discovery not available yet: %s" % e)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, "discovery failed: %s" % e)
    return W.public_space(space).model_dump(mode="json")


# ------------------------------------------------------------------ websocket

@app.websocket("/ws")
async def ws(websocket: WebSocket, run_id: str = Query("*")) -> None:
    await websocket.accept()
    loop = asyncio.get_running_loop()
    ch = None
    if run_id == "*":
        backlog, q = BUS.subscribe_all(loop)
    else:
        ch = BUS.get(run_id)
        if ch is None:
            path = replay.find_recording("%s.jsonl" % run_id)
            if path is None:
                await websocket.close(code=4404)
                return
            for ev in replay.load(path):          # a finished recording: send it and stay open
                await websocket.send_text(json.dumps(ev))
            backlog, q = [], asyncio.Queue()
        else:
            backlog, q = ch.subscribe(loop)
    try:
        for ev in backlog:
            await websocket.send_text(json.dumps(ev))
        while True:
            ev = await q.get()
            await websocket.send_text(json.dumps(ev))
    except WebSocketDisconnect:
        pass
    finally:
        if run_id == "*":
            BUS.unsubscribe_all(q)
        elif ch is not None:
            ch.unsubscribe(q)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="info")

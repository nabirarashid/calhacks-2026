"""Session API: the Onshape panel's entry point (PLAN.md B.6). Owner: W-C.

POST /api/inspect   {doc_url}          -> the document's project and live parameter values
POST /api/sessions  {doc_url, prompt}  -> parse the request, start the investigator from the
                                          values currently in Onshape, morph each accepted step
GET  /api/sessions/{run_id}/notebook   -> the lab notebook
POST /api/sessions/{run_id}/stop       -> stop after the current step (then version)

A document is matched to a project by its document id against the env var named in the
project's manifest (`cad.doc_ref`, e.g. DARWIN_DOC_WING). Document ids never leave the server.
"""
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.contracts import DesignSpace, Goal, GeometryRef, Objective, ParamValue
from shared.manifest import ProjectManifest

from backend import llm
from backend.agents import goal_parser
from backend.investigator import Investigator
from backend.run_loop import new_run_id

log = logging.getLogger("darwin.sessions")
_DID = re.compile(r"/documents/([0-9a-fA-F]{6,})")


class InspectBody(BaseModel):
    doc_url: str


class SessionBody(BaseModel):
    doc_url: str
    prompt: str
    max_sims: int = 20
    max_steps: int = 8


def doc_id(url: str) -> Optional[str]:
    m = _DID.search(url or "")
    return m.group(1).lower() if m else None


def make_router(W: Any, BUS: Any, RUNS: Dict[str, Any], is_busy: Callable[[], bool]) -> APIRouter:
    router = APIRouter()

    def project_for(doc_url: str) -> Tuple[ProjectManifest, DesignSpace]:
        did = doc_id(doc_url)
        if did:
            for pid in W.projects.ids():
                m = W.projects.get(pid)
                ref = os.environ.get(m.cad.doc_ref or "", "")
                if not ref and m.cad.doc_ref == "DARWIN_DOC_FIN":
                    ref = os.environ.get("DARWIN_FIN_DOC_URL", "")      # alias until freeze (B.6)
                if ref and doc_id(ref) == did:
                    return m, W.resolve(pid)
        raise HTTPException(404, "Darwin supports the rear wing and fin projects; this document isn't one of them")

    def live_values(doc_url: str, space: DesignSpace) -> Tuple[Dict[str, ParamValue], str]:
        """Current parameter values from the document's Variable features, else the project defaults."""
        values = {p.name: p.default for p in space.parameters}
        try:
            found = W.cad.list_variables(doc_url)
        except Exception as e:  # noqa: BLE001 — inspection must not fail the panel
            log.warning("list_variables failed: %s", e)
            return values, "unreadable"
        hits = 0
        for p in space.parameters:
            v = (found.get(p.name) or {}).get("value")
            if v is not None and p.kind != "choice":
                values[p.name] = v
                hits += 1
        return values, "onshape" if hits else "defaults"

    def current_metrics(space: DesignSpace, values: Dict[str, ParamValue], catalog: List[Any]) -> Optional[Dict[str, float]]:
        """The design's metrics now (one fast simulation), so the parser can read "25% lighter"."""
        try:
            probe = Goal(source_text="", objectives=[Objective(
                metric=next(m.name for m in catalog if m.better != "info"), direction="minimize")])
            return dict(W.sim.evaluate(space, values, probe).metrics)
        except Exception as e:  # noqa: BLE001 — without it, relative requests are refused, not misread
            log.warning("current metrics unavailable: %s", e)
            return None

    @router.post("/api/inspect")
    def inspect(body: InspectBody) -> Dict[str, Any]:
        m, space = project_for(body.doc_url)
        values, source = live_values(body.doc_url, space)
        return {"project_id": m.project_id, "source": source, "fixed": [],
                "params": [{"name": p.name, "unit": p.unit, "value": values[p.name], "min": p.min, "max": p.max,
                            "description": p.description} for p in space.parameters]}

    @router.post("/api/sessions")
    def start(body: SessionBody) -> Dict[str, Any]:
        prompt = body.prompt.strip()
        if not prompt:
            raise HTTPException(422, "prompt is required")
        if len(prompt) > 1000:
            raise HTTPException(422, "prompt is limited to 1000 characters")
        if is_busy():
            raise HTTPException(409, "a session is already running; stop it first")
        m, space = project_for(body.doc_url)
        if "optimize" not in m.authority.permitted:
            raise HTTPException(409, "project %s is level %d (optimize not permitted)"
                                % (m.project_id, m.authority.maturity))
        values, source = live_values(body.doc_url, space)
        writes = W.modes.get("cad") not in ("off",)
        if writes and source == "unreadable":     # never morph a part from values we didn't read
            raise HTTPException(503, "Couldn't read the part from Onshape (rate limit or network); try again in a moment")
        catalog = W.catalog(space.scorer)
        try:
            goal, _ = goal_parser.parse_goal(prompt, space, catalog, W.presets,
                                             current=current_metrics(space, values, catalog), current_params=values)
        except goal_parser.UnsupportedGoal as e:
            raise HTTPException(422, {"message": str(e), "unsupported": e.unsupported, "measurable": e.measurable})
        except llm.LLMUnavailable as e:
            raise HTTPException(503, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        units = {p.name: p.unit for p in space.parameters if p.cad_driven}    # sim-only params never go to Onshape
        doc_url = body.doc_url

        def apply(sp: DesignSpace, params: Dict[str, ParamValue]) -> GeometryRef:
            changed = {k: v for k, v in params.items() if k in units and v != values.get(k)}
            ref = W.cad.apply_values(doc_url, changed, units)
            if ref.status == "ready":
                values.update(changed)
            return ref

        run_id = new_run_id("session")
        inv = Investigator(W, BUS.open(run_id), space, goal, max_steps=max(1, min(body.max_steps, 12)),
                           max_sims=max(2, min(body.max_sims, 40)), start=values,
                           apply=apply if writes else None,
                           version=(lambda name: W.cad.create_version(doc_url, name)) if writes else None,
                           pack=W.packs.get(m.project_id))
        RUNS[run_id] = inv
        inv.start()
        return {"run_id": run_id, "project_id": m.project_id, "goal": goal.model_dump(mode="json"),
                "editable": inv.editable, "fixed": inv.fixed, "start_values_from": source, "writes": writes}

    def session(run_id: str) -> Investigator:
        inv = RUNS.get(run_id)
        if not isinstance(inv, Investigator):
            raise HTTPException(404, "unknown session %r" % run_id)
        return inv

    @router.get("/api/sessions/{run_id}/notebook")
    def notebook(run_id: str) -> Dict[str, Any]:
        return session(run_id).notebook.model_dump(mode="json")

    @router.post("/api/sessions/{run_id}/stop")
    def stop(run_id: str) -> Dict[str, Any]:
        inv = session(run_id)
        inv.stop()
        return {"run_id": run_id, "stopping": True}

    return router


__all__ = ["doc_id", "make_router"]

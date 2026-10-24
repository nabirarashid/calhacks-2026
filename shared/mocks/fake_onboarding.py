"""Fake onboarding for the mock server (PLAN.md v3 B.5, B.7). Zero network, in-memory.

Same request/response shapes as backend/onboarding.py (P2-C1), so the onboarding wizard
can be built end to end before the real one exists: inspect -> draft manifest + report ->
answer questions / confirm semantics (new revision each time) -> probe -> activate.
Maturity follows the B.5 rules in simplified form. It is NOT the real rules engine.
"""
import time
import uuid
from typing import Dict, List, Optional

from shared.contracts import CadSource, DesignSpace, ParamSpec
from shared.manifest import (
    PERMITTED_BY_LEVEL, ActivateResponse, Authority, CadBinding, CadInventory, CapabilityReport, InspectResponse,
    ManifestUpdate, ParamSemantics, ProjectManifest, ProjectSummary, RevisionNote,
)
from shared.mocks import fake_cad, fake_structural
from shared.mocks import make_fixtures_v2 as fx

PROJECTS = {}  # type: Dict[str, ProjectManifest]
INVENTORIES = {}  # type: Dict[str, CadInventory]


def reset() -> None:
    PROJECTS.clear()
    INVENTORIES.clear()
    for m in (fx.manifest_fin(), fx.manifest_bracket(3), fx.manifest_wing()):
        PROJECTS[m.project_id] = m


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def summaries() -> List[ProjectSummary]:
    return [ProjectSummary(project_id=m.project_id, name=m.name, revision=m.revision,
                           maturity=m.authority.maturity, domain_pack=m.domain_pack) for m in PROJECTS.values()]


def _generic_draft(project_id: str, inv: CadInventory) -> ProjectManifest:
    params = [ParamSpec(name=c.id, kind="continuous", unit=c.unit, min=c.min, max=c.max,
                        default=c.default if c.default is not None else (c.min or 0.0), cad_ref=c.id,
                        description=c.name) for c in inv.config_inputs]
    space = DesignSpace(id="%s_v1" % project_id, name=inv.document_name, scorer="none", parameters=params,
                        source=CadSource(kind="mock"), discovered=True)
    return ProjectManifest(
        project_id=project_id, revision=1, name=inv.document_name, domain_pack=None,
        cad=CadBinding(provider="mock", doc_ref="RUNTIME_" + project_id.upper()), design_space=space,
        semantics=[ParamSemantics(name=p.name, cad_ref=p.name, role="editable", meaning=p.description,
                                  confidence=0.6) for p in params],
        authority=Authority(maturity=1, permitted=PERMITTED_BY_LEVEL[1]),  # type: ignore[arg-type]
        history=[RevisionNote(revision=1, at=_now(), by="onboarding", change="Draft from inspect")])


def report(m: ProjectManifest) -> CapabilityReport:
    inv = INVENTORIES.get(m.project_id)
    found = {"config_inputs": len(m.design_space.parameters)}
    if inv is not None:
        found.update(parts=len(inv.parts), features=len(inv.features), mate_connectors=len(inv.mate_connectors))
    name = (inv.document_name if inv else m.name).lower()
    unsupported, required = [], None
    if m.domain_pack is None and "duct" in name:
        unsupported, required = ["Requires a CFD SolverAdapter (internal flow); not attempted by design."], "cfd_*"
    elif m.domain_pack is None and "heat" in name:
        unsupported, required = ["No thermal SolverAdapter installed."], "thermal_*"
    return CapabilityReport(project_id=m.project_id, maturity=m.authority.maturity, found=found,
                            missing=list(m.open_questions), unsupported=unsupported, required_adapter=required)


def inspect(doc_url: str) -> InspectResponse:
    inv = fake_cad.inspect(doc_url)
    kind = inv.document_name.lower().replace("darwin ", "").replace(" ", "")
    project_id = "%s_%s" % (kind, uuid.uuid4().hex[:4])
    if kind == "bracket":
        m = fx.manifest_bracket(1).model_copy(update={"project_id": project_id})
    else:
        m = _generic_draft(project_id, inv)
    PROJECTS[project_id] = m
    INVENTORIES[project_id] = inv
    return InspectResponse(project_id=project_id, inventory=inv, manifest=m, report=report(m))


def _level(m: ProjectManifest) -> int:
    if not all(s.confirmed for s in m.semantics):
        return 1
    if m.domain_pack is None or any(q.required_for <= 3 for q in m.open_questions):
        return 2
    return 4 if m.authority.maturity >= 4 else 3


def update(project_id: str, body: ManifestUpdate) -> ProjectManifest:
    m = PROJECTS[project_id]
    if body.revision != m.revision:
        raise ValueError("stale revision %d (current %d)" % (body.revision, m.revision))
    changes = {}  # type: Dict[str, object]
    if body.semantics is not None:
        changes["semantics"] = body.semantics
    if body.protected is not None:
        changes["protected"] = body.protected
    if body.requirements is not None:
        changes["requirements"] = body.requirements
    nxt = m.model_copy(update=changes)
    answered = set(body.answers)
    if m.domain_pack == "static_structural" and answered:
        # The mock accepts any answer to a question and fills in the fixture's confirmed values.
        full = fx.manifest_bracket(3)
        remaining = [q for q in nxt.open_questions if q.field not in answered]
        fill = {}  # type: Dict[str, object]
        if "material" in answered:
            fill["material"] = full.material
        if answered & {"load_cases[0].vector_n", "load_cases[0].fixtures"}:
            fill.update(load_cases=full.load_cases, requirements=full.requirements, analysis=full.analysis,
                        protected=full.protected)
        nxt = nxt.model_copy(update=dict(fill, open_questions=remaining))
    nxt = nxt.model_copy(update={
        "revision": m.revision + 1,
        "history": m.history + [RevisionNote(revision=m.revision + 1, at=_now(), by=body.by,
                                             change=body.note or "edited %s" % sorted(set(changes) | answered))]})
    # An edit can only lower the level (rules recomputed); only activate() raises it, with evidence.
    lvl = min(_level(nxt), m.authority.maturity)
    nxt = nxt.model_copy(update={"authority": nxt.authority.model_copy(update={
        "maturity": lvl, "permitted": PERMITTED_BY_LEVEL[lvl]})})
    PROJECTS[project_id] = nxt
    return nxt


def activate(project_id: str) -> ActivateResponse:
    m = PROJECTS[project_id]
    lvl = _level(m)
    evidence = ["semantics confirmed"] if lvl >= 2 else []
    if lvl >= 3:
        problems = fake_structural.validate_manifest(m) if m.domain_pack == "static_structural" else []
        if problems:
            lvl = 2
        else:
            evidence += ["adapter accepted manifest", "seed probe OK (mock)", "golden tests (mock)"]
    m = m.model_copy(update={"authority": m.authority.model_copy(update={
        "maturity": lvl, "permitted": PERMITTED_BY_LEVEL[lvl], "evidence": evidence})})
    PROJECTS[project_id] = m
    return ActivateResponse(maturity=lvl, evidence=evidence, report=report(m))  # type: ignore[arg-type]


def get(project_id: str) -> Optional[ProjectManifest]:
    return PROJECTS.get(project_id)


reset()

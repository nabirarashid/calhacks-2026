"""Env-driven choice of real vs fake components. The ONLY place backend picks implementations.

DARWIN_SIM=real|fake   DARWIN_CAD=real|fake|off   DARWIN_LLM_PROVIDER=anthropic|mock|replay
A "real" component that cannot be imported falls back to its fake, and /api/health says so.
"""
import importlib
import json
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Optional

from shared.contracts import DesignSpace, GeometryRef, OnshapeBudget, ParamValue, Preset, geometry_key
from shared.manifest import ProjectManifest

from backend import adapters, llm
from backend.agents.base import bind_pack
from backend.projects import ProjectRegistry

log = logging.getLogger("darwin.wiring")
ROOT = Path(__file__).resolve().parent.parent
# Closed-form stand-ins used only while a real scorer is missing from sim (PLAN.md B.10).
FALLBACK_SCORERS = {"rear_wing_v1": "shared.mocks.fake_wing"}
FIXTURES = ROOT / "shared" / "fixtures"


class _OffCad:
    """DARWIN_CAD=off: never touches Onshape; serves only what is already cached."""

    def __init__(self, fallback: ModuleType) -> None:
        self._fake = fallback

    def build_geometry(self, space: DesignSpace, params: Dict[str, ParamValue], *, allow_network: bool = True) -> GeometryRef:
        return self._fake.build_geometry(space, params, allow_network=False)

    def geometry_file(self, key: str) -> Optional[Path]:
        return self._fake.geometry_file(key)

    def budget_status(self) -> OnshapeBudget:
        return OnshapeBudget(account_label="off", calls_session=0, calls_ledger_total=0, remaining_estimate=0,
                             reserve=0, reserve_unlocked=False, hard_stop=True)

    def commit_to_document(self, space: DesignSpace, params: Dict[str, ParamValue]) -> GeometryRef:
        return GeometryRef(geometry_key=geometry_key(space, params), status="skipped", source="none", error="cad_off")

    def discover_design_space(self, doc_url: str, *, probe: bool = False) -> DesignSpace:
        raise RuntimeError("CAD is off")

    def export_print_package(self, space: DesignSpace, params: Dict[str, ParamValue], out_dir: Path) -> Path:
        return self._fake.export_print_package(space, params, out_dir)

    def list_variables(self, doc_url: str) -> Dict[str, Dict[str, object]]:
        raise RuntimeError("CAD is off")

    def apply_values(self, doc_url: str, params: Dict[str, ParamValue], units: Dict[str, str]) -> GeometryRef:
        return GeometryRef(geometry_key="off", status="skipped", source="none", error="cad_off")

    def create_version(self, doc_url: str, name: str) -> Optional[str]:
        return None


class Wiring:
    def __init__(self) -> None:
        self.modes = {}  # type: Dict[str, str]
        self.sim = self._load("sim", os.environ.get("DARWIN_SIM", "real"), "sim.api", "shared.mocks.fake_sim")
        cad_mode = os.environ.get("DARWIN_CAD", "real")
        if cad_mode == "off":
            self.cad = _OffCad(importlib.import_module("shared.mocks.fake_cad"))
            self.modes["cad"] = "off"
        else:
            self.cad = self._load("cad", cad_mode, "cad.api", "shared.mocks.fake_cad")
        self.modes["llm"] = llm.provider_name()
        self.modes["mode"] = os.environ.get("DARWIN_MODE", "live")
        self.projects = ProjectRegistry()
        self.spaces = {}  # type: Dict[str, DesignSpace]          # runtime spaces (doc_url resolved)
        self.space_project = {}  # type: Dict[str, str]           # space id -> project id
        self.packs = {}  # type: Dict[str, object]                # project id -> domain pack
        for pid in self.projects.ids():
            self._activate(self.projects.get(pid))
        self.presets = [Preset.model_validate(p) for p in json.loads((FIXTURES / "presets.json").read_text())]

    def _load(self, name: str, mode: str, real: str, fake: str):
        if mode == "real":
            try:
                mod = importlib.import_module(real)
                self.modes[name] = "real"
                return mod
            except Exception as e:  # noqa: BLE001 — any import problem means "not ready yet"
                log.warning("%s: real module %s unavailable (%s); using %s", name, real, e, fake)
                self.modes[name] = "fake(fallback)"
                return importlib.import_module(fake)
        self.modes[name] = "fake"
        return importlib.import_module(fake)

    def _activate(self, m: ProjectManifest) -> None:
        """Make a project runnable: resolve its CAD ref, bind its domain pack, bridge its solver."""
        space = m.design_space
        url = os.environ.get(m.cad.doc_ref) if m.cad.doc_ref else None
        if not url and m.cad.doc_ref == "DARWIN_DOC_FIN":
            url = os.environ.get("DARWIN_FIN_DOC_URL")       # alias until freeze (PLAN.md v3 B.6)
        if url:
            space = space.model_copy(update={"source": space.source.model_copy(update={"doc_url": url})})
        if m.domain_pack:
            try:
                from domains import get_pack
                pack = get_pack(m.domain_pack)
                self.packs[m.project_id] = pack
                bind_pack(space.id, pack)
            except KeyError as e:
                log.warning("project %s: %s", m.project_id, e)
        if space.scorer in FALLBACK_SCORERS and self.modes.get("sim") == "real":
            try:
                self.sim.metric_catalog(space.scorer)
            except KeyError:        # the real solver hasn't landed yet: use the closed-form stand-in
                plugin = importlib.import_module(FALLBACK_SCORERS[space.scorer]).PLUGIN
                self.sim.register_scorer(space.scorer, plugin)
                self.modes[space.scorer] = "fake(fallback)"
                log.warning("scorer %s not in sim; using %s", space.scorer, FALLBACK_SCORERS[space.scorer])
        if m.analysis and m.analysis.screening_adapter in adapters.SOLVERS and "optimize" in m.authority.permitted:
            if self.modes.get("sim") != "real":
                log.warning("project %s needs DARWIN_SIM=real for its %s adapter", m.project_id,
                            m.analysis.screening_adapter)
            else:
                verify = m.analysis.verify_adapter
                bridge = adapters.ScorerBridge(m, adapters.get_solver(m.analysis.screening_adapter),
                                               adapters.get_solver(verify) if verify in adapters.SOLVERS else None)
                sid = adapters.scorer_id(m)
                self.sim.register_scorer(sid, bridge)
                space = space.model_copy(update={"scorer": sid})
        self.spaces[space.id] = space
        self.space_project[space.id] = m.project_id

    def project_for_space(self, space_id: str) -> Optional[ProjectManifest]:
        pid = self.space_project.get(space_id)
        return self.projects.get(pid) if pid else None

    def resolve(self, ref: str) -> DesignSpace:
        """A project id or a design space id (the v1 alias, e.g. "fin_v1") -> its runtime space."""
        if ref in self.spaces:
            return self.spaces[ref]
        for sid, pid in self.space_project.items():
            if pid == ref:
                return self.spaces[sid]
        raise KeyError(ref)

    def public_manifest(self, m: ProjectManifest) -> ProjectManifest:
        """Manifests hold env var names only; strip the space's runtime doc_url defensively."""
        return m.model_copy(update={"design_space": self.public_space(m.design_space)})

    def public_space(self, space: DesignSpace) -> DesignSpace:
        """Strip runtime-only fields (doc_url) before anything leaves the process."""
        return space.model_copy(update={"source": space.source.model_copy(update={"doc_url": None})})

    def catalog(self, scorer: str):
        return self.sim.metric_catalog(scorer)

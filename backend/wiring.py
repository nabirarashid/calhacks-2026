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

from backend import llm

log = logging.getLogger("darwin.wiring")
ROOT = Path(__file__).resolve().parent.parent
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
        self.spaces = {s.id: s for s in self._load_spaces()}
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

    def _load_spaces(self) -> List[DesignSpace]:
        fin = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
        # The current Onshape Part Studio has square edges and no profile input.
        # Preserve the frozen fixture for historical recordings, but constrain
        # every new live run to the geometry the CAD document can reproduce.
        fin = fin.model_copy(update={
            "parameters": [
                p.model_copy(update={"choices": ["square"], "default": "square",
                                     "cad_driven": False})
                if p.name == "edge_profile" else p
                for p in fin.parameters
            ]
        })
        url = os.environ.get("DARWIN_FIN_DOC_URL")
        if url:
            fin = fin.model_copy(update={"source": fin.source.model_copy(update={"doc_url": url})})
        return [fin]

    def public_space(self, space: DesignSpace) -> DesignSpace:
        """Strip runtime-only fields (doc_url) before anything leaves the process."""
        return space.model_copy(update={"source": space.source.model_copy(update={"doc_url": None})})

    def catalog(self, scorer: str):
        return self.sim.metric_catalog(scorer)

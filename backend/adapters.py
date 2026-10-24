"""Registered solver adapters, by stable id (PLAN.md v3 B.4), and the bridge into the run loop.

The run loop scores designs through sim.api (scorer plugins keyed by DesignSpace.scorer). A
non-fin project instead names a SolverAdapter in its manifest. ScorerBridge binds one adapter
to one manifest and presents it as a scorer plugin, so a new domain runs through the existing
run loop unchanged. Ids come only from this table: nothing under a drafts/ folder, and nothing
named by model output, is ever imported.
"""
import importlib
from typing import Any, Dict, List, Mapping, Optional

from shared.contracts import DesignSpace, Goal, MetricInfo, ParamValue
from shared.manifest import ProjectManifest

SOLVERS = {
    "structural_analytic_v1": "sim.adapters.structural_analytic_v1",
    "fake_structural": "shared.mocks.fake_structural",
}  # type: Dict[str, str]


def get_solver(adapter_id: str) -> Any:
    if adapter_id not in SOLVERS:
        raise KeyError("solver adapter %r is not registered" % adapter_id)
    return importlib.import_module(SOLVERS[adapter_id])


def register_solver(adapter_id: str, module_path: str) -> None:
    if "drafts" in module_path.split("."):
        raise ValueError("draft adapters are never registered")
    SOLVERS[adapter_id] = module_path


class ScorerBridge:
    """One project's SolverAdapter(s), shaped like a sim.plugins.ScorerPlugin."""

    def __init__(self, manifest: ProjectManifest, screening: Any, verify: Optional[Any] = None) -> None:
        self.m = manifest
        self.screening = screening
        self.verify = verify

    def metric_catalog(self) -> List[MetricInfo]:
        return self.screening.metric_catalog()

    def _eval(self, adapter: Any, params: Mapping[str, ParamValue], goal: Optional[Goal], fidelity: str) -> Any:
        from sim.plugins import PluginEvaluation
        g = goal or Goal(source_text="", objectives=[], constraints=[])
        score, art = adapter.evaluate(self.m, dict(params), g, fidelity=fidelity)
        return PluginEvaluation(metrics=dict(score.metrics), warnings=list(score.warnings) + list(art.validity),
                                diagnostics=dict(art.diagnostics))

    def metrics(self, space: DesignSpace, params: Mapping[str, ParamValue],
                goal: Optional[Goal] = None) -> Dict[str, float]:
        return self._eval(self.screening, params, goal, "screening").metrics

    def evaluate_metrics(self, space: DesignSpace, params: Mapping[str, ParamValue], goal: Optional[Goal] = None,
                         fidelity: str = "fast") -> Any:
        if fidelity == "high":
            return self.hifi(space, params, goal)
        return self._eval(self.screening, params, goal, "screening")

    def hifi(self, space: DesignSpace, params: Mapping[str, ParamValue], goal: Optional[Goal] = None) -> Any:
        return self._eval(self.verify or self.screening, params, goal, "verification")


def scorer_id(manifest: ProjectManifest) -> str:
    return "%s:%s" % (manifest.analysis.screening_adapter if manifest.analysis else "none", manifest.project_id)


__all__ = ["SOLVERS", "get_solver", "register_solver", "ScorerBridge", "scorer_id"]

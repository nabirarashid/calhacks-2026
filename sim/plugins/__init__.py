"""Scorer plugin protocol used by :mod:`sim.api`.

Plugins stay independent of ``sim.api`` to avoid registry/import cycles.  The
API owns aggregation; a plugin only supplies raw metrics and physics warnings.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Protocol

from shared.contracts import DesignSpace, Goal, MetricInfo, ParamValue


@dataclass(frozen=True)
class PluginEvaluation:
    metrics: Dict[str, float]
    warnings: List[str]
    diagnostics: Dict[str, float] = field(default_factory=dict)


class ScorerPlugin(Protocol):
    """Structural interface for deterministic physics scorers."""

    def metric_catalog(self) -> List[MetricInfo]:
        ...

    def metrics(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
    ) -> Dict[str, float]:
        ...

    def evaluate_metrics(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
        fidelity: str = "fast",
    ) -> PluginEvaluation:
        ...

    def hifi(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
    ) -> PluginEvaluation:
        ...


__all__ = ["PluginEvaluation", "ScorerPlugin"]

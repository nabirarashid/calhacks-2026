"""Darwin contracts v2 — adapter protocols (PLAN.md weekend plan v3, B.4). FROZEN at CP5.

The core (backend/, cad/) composes registered capabilities by stable id through these
interfaces and imports nothing domain-specific. An LLM never names or loads an adapter
that is not registered, and nothing under a `drafts/` folder is ever registered.
Structural typing: implementations don't inherit from these, they just match them.
"""
from typing import Dict, List, Mapping, Optional, Protocol, Tuple

from shared.contracts import AnalysisArtifact, GeometryRef, Goal, MetricInfo, ParamValue, Score
from shared.manifest import (
    AdapterCapability, BlockingQuestion, CadInventory, CheckResult, GeometryEvidence, ProbeResult,
    ProjectManifest,
)

Params = Mapping[str, ParamValue]


class CadAdapter(Protocol):
    def capability(self) -> AdapterCapability: ...

    def inspect(self, doc_ref: str) -> CadInventory:
        """Read-only inventory, <= 6 Onshape calls. `doc_ref` is an env var name or `runtime:<uuid>`."""
        ...

    def probe(self, m: ProjectManifest, cases: List[Dict[str, ParamValue]]) -> List[ProbeResult]:
        """Regenerate each case (<= 9, cached); never writes."""
        ...

    def build_geometry(self, m: ProjectManifest, params: Params, *, fmt: str = "stl") -> GeometryRef:
        """Configured export (no document write). Stale source microversion => status 'failed'."""
        ...

    def preview_commit(self, m: ProjectManifest, params: Params) -> Dict[str, object]:
        """What a commit would do (see manifest.CommitPreview). 0-1 calls, no writes."""
        ...

    def commit(self, m: ProjectManifest, params: Params, approval: Dict[str, object]) -> GeometryRef:
        """Apply -> read back -> verify -> version, on the isolated write target only."""
        ...


class SolverAdapter(Protocol):
    def capability(self) -> AdapterCapability: ...

    def metric_catalog(self) -> List[MetricInfo]: ...

    def validate_manifest(self, m: ProjectManifest) -> List[BlockingQuestion]:
        """Empty list = the adapter accepts the manifest. Missing/unconfirmed inputs => questions."""
        ...

    def evaluate(self, m: ProjectManifest, params: Params, goal: Goal, *,
                 geometry: Optional[str] = None, fidelity: str = "screening") -> Tuple[Score, AnalysisArtifact]:
        """Deterministic. `geometry` is a local STL/STEP path for verification-fidelity adapters."""
        ...

    def convergence_check(self, m: ProjectManifest, params: Params, geometry: str) -> CheckResult:
        """Two-level refinement on one design. passed=None if it could not run."""
        ...


class GeometryVerifier(Protocol):
    def verify(self, m: ProjectManifest, params: Params, stl_path: str) -> GeometryEvidence: ...


class DomainPack(Protocol):
    """A module domains/<pack_id>/pack.py exposing PACK with these attributes."""

    pack_id: str
    version: str
    solver_ids: List[str]                      # approved adapters, by registered id
    verifier: GeometryVerifier
    questions: List[BlockingQuestion]          # the required question set
    prompt_fragment: str                       # domain wording for proposer/critic/goal-parser prompts
    headline_metrics: List[str]                # replaces run_loop's hard-coded drag_n/stability_margin_cal
    limitations: List[str]                     # replaces evidence.py's fin text
    renderer: Optional[str]                    # "fin_morph" | None (=> GeometryViewer only)

    def signature_match(self, inv: CadInventory) -> float:
        """Deterministic match score in [0, 1]; >= 0.5 makes the pack a candidate."""
        ...


__all__ = ["Params", "CadAdapter", "SolverAdapter", "GeometryVerifier", "DomainPack"]

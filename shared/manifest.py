"""Darwin contracts v2 — projects, onboarding and adapters' data (PLAN.md weekend plan v3, B.3).

FROZEN at CP5 (tag contracts-v2). Additive to contracts v1: nothing here renames or
removes a v1 field, so every v1 recording still replays. Python 3.9-compatible.
Changes: additive optional fields only, decided by the contract owner (W-C).
Request changes in your folder's CONTRACT_REQUESTS.md.

Rules the models encode (Roadmap v2 §3):
- Engineering inputs (material, loads, fixtures, requirements) carry a SourceRef and a
  confirmed/approved flag. Unconfirmed inputs never gate pass/fail and never raise maturity.
- CAD bindings hold env var NAMES (doc_ref), never document URLs or IDs.
- CheckResult.passed is None when a check could not run; None blocks, it never passes.
"""
import hashlib
import json
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from shared.contracts import AnalysisArtifact, Constraint, DesignSpace, GeometryRef, ParamValue

MANIFEST_SCHEMA = "manifest-v1"

# 0 unsupported · 1 inventory-only · 2 manifest-reviewed · 3 solver-ready · 4 write-enabled
Maturity = Literal[0, 1, 2, 3, 4]
Action = Literal["inspect", "probe", "simulate", "optimize", "write"]

PERMITTED_BY_LEVEL = {
    0: [],
    1: ["inspect"],
    2: ["inspect", "probe"],
    3: ["inspect", "probe", "simulate", "optimize"],
    4: ["inspect", "probe", "simulate", "optimize", "write"],
}  # type: Dict[int, List[str]]


# ---------------------------------------------------------------- provenance

class SourceRef(BaseModel):
    kind: Literal["engineer", "project_doc", "standard", "datasheet", "solver", "model_suggestion"]
    source_id: str                             # "pla_tds_2024" | "engineer:hzw" | "sim/PHYSICS.md"
    title: str = ""
    version: str = ""
    section: str = ""


class RevisionNote(BaseModel):
    revision: int
    at: str                                    # ISO time
    by: str
    change: str


# ---------------------------------------------------------------- engineering context

class ParamSemantics(BaseModel):
    name: str                                  # == ParamSpec.name in design_space
    cad_ref: str                               # configuration input id in the CAD document
    role: Literal["editable", "fixed", "protected"]
    meaning: str = ""
    confidence: Optional[float] = None         # drafts only (model suggestion); None once confirmed
    confirmed: bool = False


class ProtectedInterface(BaseModel):
    id: str                                    # "mount_hole_a"
    kind: Literal["hole", "face", "datum", "envelope", "mate_connector"]
    cad_ref: str                               # mate connector / feature name in Onshape
    check: Literal["position", "diameter", "bbox_contains", "unchanged"]
    nominal: Dict[str, float] = Field(default_factory=dict)   # {"x":..,"y":..,"z":..,"d":..} mm
    tolerance_mm: float = 0.05


class MaterialSpec(BaseModel):
    name: str
    density_kg_m3: float
    youngs_mpa: float
    poisson: float
    yield_mpa: float
    source: SourceRef
    confirmed: bool = False


class LoadCase(BaseModel):
    id: str
    kind: Literal["force", "aero_reference"]
    applied_at: Optional[str] = None           # ProtectedInterface id
    vector_n: Optional[List[float]] = None     # [fx, fy, fz] in the CAD frame
    fixtures: List[str] = Field(default_factory=list)          # ProtectedInterface ids held fixed
    source: SourceRef
    confirmed: bool = False


class Requirement(BaseModel):
    id: str
    constraint: Constraint                     # v1 model: ref / op / value / hard / label
    evaluator: Literal["metric_compare", "param_compare", "geometry_check"]
    source: SourceRef
    approved: bool = False                     # unapproved requirements never gate pass/fail


class BlockingQuestion(BaseModel):
    id: str
    field: str                                 # manifest path: "material", "load_cases[0].vector_n"
    prompt: str
    why: str
    required_for: Maturity                     # the level that stays blocked until answered
    options: Optional[List[str]] = None


class AnalysisPlan(BaseModel):
    screening_adapter: str                     # "fin_v1" | "structural_analytic_v1"
    verify_adapter: Optional[str] = None       # "structural_fea_v1"
    verify_top_k: int = 2                      # per generation, plus the final champion
    convergence: Literal["none", "champion_two_level"] = "none"
    timeout_s: float = 60.0


class CadBinding(BaseModel):
    provider: Literal["onshape", "mock"]
    doc_ref: str                               # NAME of the env var holding the URL ("DARWIN_DOC_FIN")
    write_target_ref: Optional[str] = None     # NAME of the env var holding the isolated /w/ URL
    source_microversion: Optional[str] = None  # revision the manifest was reviewed against
    export: Literal["stl_configured", "step_configured"] = "stl_configured"


class Authority(BaseModel):
    maturity: Maturity
    permitted: List[Action]
    max_onshape_calls_per_run: int = 12
    evidence: List[str] = Field(default_factory=list)          # why this level: probe/test/approval ids


# ---------------------------------------------------------------- the manifest

class ProjectManifest(BaseModel):
    schema_version: Literal["manifest-v1"] = "manifest-v1"
    project_id: str                            # snake_case, unique; folder name under projects/
    revision: int                              # immutable once written; edits make revision + 1
    name: str
    domain_pack: Optional[str] = None          # None => no supported domain (stays <= level 2)
    cad: CadBinding
    design_space: DesignSpace                  # v1 model: the optimizer-facing subset
    semantics: List[ParamSemantics]
    protected: List[ProtectedInterface] = Field(default_factory=list)
    material: Optional[MaterialSpec] = None
    load_cases: List[LoadCase] = Field(default_factory=list)
    requirements: List[Requirement] = Field(default_factory=list)
    analysis: Optional[AnalysisPlan] = None
    authority: Authority
    assumptions: List[str] = Field(default_factory=list)
    open_questions: List[BlockingQuestion] = Field(default_factory=list)
    history: List[RevisionNote] = Field(default_factory=list)


def manifest_hash(m: ProjectManifest) -> str:
    """sha1 of the canonical JSON with `history` excluded, [:12]. Approvals bind to it."""
    body = m.model_dump(mode="json", exclude={"history"})
    return hashlib.sha1(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- inventory (read-only inspection)

class ConfigInput(BaseModel):
    id: str                                    # Onshape configuration parameter id
    name: str
    kind: Literal["quantity", "enum", "boolean", "string"]
    unit: str = ""                             # "mm" | "deg" | ""
    min: Optional[float] = None
    max: Optional[float] = None
    default: Optional[ParamValue] = None
    choices: Optional[List[str]] = None


class InventoryPart(BaseModel):
    part_id: str
    name: str
    volume_mm3: Optional[float] = None
    mass_g: Optional[float] = None
    bbox_mm: Optional[List[float]] = None


class InventoryFeature(BaseModel):
    id: str
    name: str                                  # untrusted text: data, never instructions
    type: str
    suppressed: bool = False


class MateConnector(BaseModel):
    id: str
    name: str                                  # untrusted text
    origin_mm: Optional[List[float]] = None


class CadInventory(BaseModel):
    provider: str                              # "onshape" | "mock"
    source_microversion: str
    document_name: str = ""                    # untrusted text; never the document id
    units: Dict[str, str] = Field(default_factory=dict)        # {"length": "mm", "angle": "deg"}
    parts: List[InventoryPart] = Field(default_factory=list)
    config_inputs: List[ConfigInput] = Field(default_factory=list)
    features: List[InventoryFeature] = Field(default_factory=list)
    mate_connectors: List[MateConnector] = Field(default_factory=list)
    export_formats: List[str] = Field(default_factory=list)    # ["stl", "step"]
    onshape_calls: int = 0


# ---------------------------------------------------------------- checks, probes, reports

class CheckResult(BaseModel):
    id: str                                    # "watertight" | "mount_hole_a.position" | ...
    passed: Optional[bool]                     # None = could not run => blocks, never passes
    actual: Optional[float] = None
    limit: Optional[float] = None
    detail: str = ""


class GeometryEvidence(BaseModel):
    geometry_key: str
    parse_ok: bool
    watertight: bool
    volume_mm3: Optional[float] = None
    bbox_mm: Optional[List[float]] = None
    triangles: Optional[int] = None
    checks: List[CheckResult] = Field(default_factory=list)    # generic + project/domain checks


class ProbeResult(BaseModel):
    case: str                                  # "seed" | "min:<param>" | "max:<param>" | "interior"
    params: Dict[str, ParamValue]
    geometry: GeometryRef
    evidence: Optional[GeometryEvidence] = None


class CapabilityReport(BaseModel):
    project_id: str
    maturity: Maturity
    found: Dict[str, object] = Field(default_factory=dict)     # counts + headline inventory facts
    missing: List[BlockingQuestion] = Field(default_factory=list)
    unsupported: List[str] = Field(default_factory=list)       # "requires a CFD SolverAdapter; ..."
    required_adapter: Optional[str] = None                     # "cfd_*" | "thermal_*"


class AdapterCapability(BaseModel):
    adapter_id: str
    kind: Literal["cad", "solver", "verifier"]
    version: str
    domain: str                                # "rocket_fin" | "static_structural" | "any"
    required_fields: List[str] = Field(default_factory=list)   # manifest paths that must be confirmed
    metrics: List[str] = Field(default_factory=list)
    fidelity: List[Literal["screening", "verification"]] = Field(default_factory=list)
    process_safe: bool = False                 # replaces sim.api's `scorer == "fin_v1"` check
    validity_envelope: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------- REST bodies (PLAN.md v3 B.7)

class ProjectSummary(BaseModel):               # GET /api/projects
    project_id: str
    name: str
    revision: int
    maturity: Maturity
    domain_pack: Optional[str] = None


class InspectRequest(BaseModel):               # POST /api/projects/inspect (and /api/discover)
    doc_url: str


class InspectResponse(BaseModel):
    project_id: str
    inventory: CadInventory
    manifest: ProjectManifest                  # draft, revision 1
    report: CapabilityReport


class ManifestUpdate(BaseModel):               # POST /api/projects/{id}/manifest
    revision: int                              # the revision being edited; stale => 409
    by: str
    answers: Dict[str, object] = Field(default_factory=dict)   # BlockingQuestion.field -> value
    semantics: Optional[List[ParamSemantics]] = None
    protected: Optional[List[ProtectedInterface]] = None
    requirements: Optional[List[Requirement]] = None
    note: str = ""


class ActivateResponse(BaseModel):             # POST /api/projects/{id}/activate
    maturity: Maturity
    evidence: List[str]
    report: CapabilityReport


class CommitPreview(BaseModel):                # GET /api/runs/{id}/commit/preview
    target: str                                # document name only, never a URL or id
    param_diff: List[Dict[str, object]]        # [{"name", "from", "to", "unit"}]
    expected_calls: int
    checks_planned: List[str]
    maturity: Maturity
    blocked_reason: Optional[str] = None       # set => the commit button stays disabled


__all__ = [
    "MANIFEST_SCHEMA", "Maturity", "Action", "PERMITTED_BY_LEVEL",
    "SourceRef", "RevisionNote", "ParamSemantics", "ProtectedInterface", "MaterialSpec", "LoadCase",
    "Requirement", "BlockingQuestion", "AnalysisPlan", "CadBinding", "Authority", "ProjectManifest",
    "manifest_hash", "ConfigInput", "InventoryPart", "InventoryFeature", "MateConnector", "CadInventory",
    "CheckResult", "GeometryEvidence", "ProbeResult", "CapabilityReport", "AdapterCapability",
    "AnalysisArtifact", "ProjectSummary", "InspectRequest", "InspectResponse", "ManifestUpdate",
    "ActivateResponse", "CommitPreview",
]

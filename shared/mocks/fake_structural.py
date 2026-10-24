"""Fake SolverAdapter for the static_structural domain (PLAN.md v3 B.9). Zero network, ~1 ms.

A closed-form cantilever L-bracket so the backend and dashboard never wait for FEA:
the horizontal flange is a T-section (plate + optional top rib) loaded at the load hole,
with a stress-concentration factor at the root mounting holes. Plausible magnitudes,
deterministic, monotone in the right directions (thicker -> stiffer, holes -> lighter
but weaker). It is NOT the real adapter: W-B's structural_analytic_v1 / structural_fea_v1
replace it. Also owns the bracket design space and metric catalog used by the v2 fixtures.
"""
import math
import time
from typing import Dict, List, Mapping, Optional, Tuple

from shared.contracts import (
    AnalysisArtifact, CadSource, DesignSpace, Goal, MetricInfo, ParamSpec, ParamValue, Score, canonicalize,
)
from shared.manifest import AdapterCapability, BlockingQuestion, CheckResult, ProjectManifest
from shared.mocks.fake_sim import aggregate

ADAPTER_ID = "fake_structural"
VERSION = "0.1.0"
WIDTH_MM = 30.0          # bracket width (fixed context)
UPRIGHT_MM = 40.0        # vertical (wall) flange height (fixed context)
HOLE_D_MM = 5.0          # lightening hole diameter

BRACKET_SPACE = DesignSpace(
    id="bracket_v1",
    name="Cantilever L-bracket",
    scorer="static_structural",
    parameters=[
        ParamSpec(name="thickness", kind="continuous", unit="mm", min=2.0, max=8.0, step=0.1, default=5.0,
                  cad_ref="thickness", description="Flange plate thickness"),
        ParamSpec(name="flange_length", kind="continuous", unit="mm", min=40.0, max=120.0, step=0.5,
                  default=80.0, cad_ref="flange_length", description="Wall to load hole"),
        ParamSpec(name="rib_height", kind="continuous", unit="mm", min=0.0, max=20.0, step=0.5, default=8.0,
                  cad_ref="rib_height", description="Top stiffening rib height (0 = no rib)"),
        ParamSpec(name="rib_thickness", kind="continuous", unit="mm", min=1.5, max=6.0, step=0.1, default=3.0,
                  cad_ref="rib_thickness", description="Rib wall thickness"),
        ParamSpec(name="fillet_radius", kind="continuous", unit="mm", min=1.0, max=8.0, step=0.5, default=3.0,
                  cad_ref="fillet_radius", description="Inside corner fillet"),
        ParamSpec(name="lightening_holes", kind="integer", unit="", min=0, max=3, default=0,
                  cad_ref="lightening_holes", description="Number of lightening holes in the flange"),
    ],
    context={"width_mm": WIDTH_MM, "upright_mm": UPRIGHT_MM},
    source=CadSource(kind="mock", mode="configuration", model_revision="r1"),
    notes=["Fixture ranges. W-A owns the real Part Studio ranges; W-B owns the real adapter."],
)

CATALOG = [
    MetricInfo(name="mass_g", unit="g", description="Bracket mass", better="lower",
               typical_min=5.0, typical_max=60.0),
    MetricInfo(name="tip_deflection_mm", unit="mm", description="Deflection at the load hole", better="lower",
               typical_min=0.0, typical_max=5.0),
    MetricInfo(name="stress_max_mpa", unit="MPa", description="Peak bending stress away from holes",
               better="lower", typical_min=0.0, typical_max=60.0),
    MetricInfo(name="stress_hole_mpa", unit="MPa", description="Peak stress at the protected mounting holes",
               better="lower", typical_min=0.0, typical_max=80.0),
    MetricInfo(name="safety_factor", unit="", description="Yield / governing stress", better="higher",
               typical_min=0.5, typical_max=6.0),
]  # type: List[MetricInfo]


def capability() -> AdapterCapability:
    return AdapterCapability(
        adapter_id=ADAPTER_ID, kind="solver", version=VERSION, domain="static_structural",
        required_fields=["material", "load_cases[0].vector_n", "load_cases[0].fixtures"],
        metrics=[m.name for m in CATALOG], fidelity=["screening", "verification"], process_safe=True,
        validity_envelope={"material": "linear elastic", "deflection": "small (< 10% of flange length)",
                           "stress": "below yield"},
    )


def metric_catalog() -> List[MetricInfo]:
    return [m.model_copy() for m in CATALOG]


def validate_manifest(m: ProjectManifest) -> List[BlockingQuestion]:
    """Every missing or unconfirmed engineering input becomes a blocking question (never a default)."""
    out = []  # type: List[BlockingQuestion]
    if m.material is None or not m.material.confirmed:
        out.append(BlockingQuestion(id="material", field="material", required_for=3,
                                    prompt="Which material, and from which source (datasheet or test)?",
                                    why="Yield strength and stiffness set every stress and deflection result."))
    lc = m.load_cases[0] if m.load_cases else None
    if lc is None or not lc.confirmed or not lc.vector_n:
        out.append(BlockingQuestion(id="load", field="load_cases[0].vector_n", required_for=3,
                                    prompt="What load acts on the load hole (newtons, direction)?",
                                    why="Darwin never assumes a load."))
    if lc is None or not lc.fixtures:
        out.append(BlockingQuestion(id="fixtures", field="load_cases[0].fixtures", required_for=3,
                                    prompt="Which interfaces are bolted to the wall?",
                                    why="The boundary condition decides where the bracket bends."))
    return out


def _section(t: float, rib_h: float, rib_t: float) -> Tuple[float, float]:
    """Second moment (mm^4) and extreme-fibre distance (mm) of plate WIDTH x t plus a centred top rib."""
    a1, y1 = WIDTH_MM * t, t / 2.0
    a2, y2 = rib_t * rib_h, t + rib_h / 2.0
    area = a1 + a2
    yc = (a1 * y1 + a2 * y2) / area
    i1 = WIDTH_MM * t ** 3 / 12.0 + a1 * (y1 - yc) ** 2
    i2 = rib_t * rib_h ** 3 / 12.0 + a2 * (y2 - yc) ** 2
    return i1 + i2, max(yc, t + rib_h - yc)


def metrics(m: ProjectManifest, params: Mapping[str, ParamValue]) -> Dict[str, float]:
    p = canonicalize(m.design_space, dict(params))
    t, length = float(p["thickness"]), float(p["flange_length"])
    rib_h, rib_t, fillet = float(p["rib_height"]), float(p["rib_thickness"]), float(p["fillet_radius"])
    holes = int(p["lightening_holes"])
    mat = m.material
    force = abs(m.load_cases[0].vector_n[1]) if m.load_cases and m.load_cases[0].vector_n else 0.0
    inertia, c = _section(t, rib_h, rib_t)
    inertia *= (1.0 - 0.06 * holes)                     # holes remove flange material near the axis
    moment = force * length                             # N*mm at the wall
    stress = moment * c / inertia                       # MPa
    kt = 1.0 + 1.6 / (1.0 + fillet / t)                 # sharper corner -> higher concentration
    stress_hole = kt * stress * (1.0 + 0.12 * holes)
    e_mpa = mat.youngs_mpa if mat else 3500.0
    deflection = force * length ** 3 / (3.0 * e_mpa * inertia)
    vol = (length * WIDTH_MM * t + UPRIGHT_MM * WIDTH_MM * t + length * rib_h * rib_t
           - holes * math.pi * (HOLE_D_MM / 2.0) ** 2 * t)
    rho = mat.density_kg_m3 if mat else 1240.0
    yield_mpa = mat.yield_mpa if mat else 50.0
    governing = max(stress, stress_hole, 1e-6)
    return {"mass_g": vol * rho * 1e-6, "tip_deflection_mm": deflection, "stress_max_mpa": stress,
            "stress_hole_mpa": stress_hole, "safety_factor": yield_mpa / governing}


def evaluate(m: ProjectManifest, params: Mapping[str, ParamValue], goal: Goal, *,
             geometry: Optional[str] = None, fidelity: str = "screening",
             design_id: str = "") -> Tuple[Score, AnalysisArtifact]:
    t0 = time.perf_counter()
    if validate_manifest(m):
        raise ValueError("manifest is not solver-ready: %s" % [q.id for q in validate_manifest(m)])
    p = canonicalize(m.design_space, dict(params))
    mets = metrics(m, p)
    mesh = {}  # type: Dict[str, float]
    if fidelity == "verification":                      # pretend FEA: slightly higher hole stress
        mets = dict(mets, stress_hole_mpa=mets["stress_hole_mpa"] * 1.06)
        mets["safety_factor"] = (m.material.yield_mpa if m.material else 50.0) / max(
            mets["stress_max_mpa"], mets["stress_hole_mpa"])
        mesh = {"nodes": 18240.0, "elements": 11010.0, "h_mm": 1.2, "level": 1.0}
    obj, viols, feasible, agg = aggregate(m.design_space, p, mets, goal, CATALOG)
    score = Score(metrics={k: round(v, 4) for k, v in mets.items()}, objective_scores=obj, violations=viols,
                  feasible=feasible, aggregate=round(agg, 5),
                  fidelity="high" if fidelity == "verification" else "fast",
                  eval_ms=(time.perf_counter() - t0) * 1000.0)
    validity = []
    if mets["tip_deflection_mm"] > 0.1 * float(p["flange_length"]):
        validity.append("deflection exceeds the small-deflection envelope")
    if mets["safety_factor"] < 1.0:
        validity.append("stress exceeds yield: linear-elastic result is not valid past this point")
    art = AnalysisArtifact(design_id=design_id, adapter_id=ADAPTER_ID, adapter_version=VERSION,
                           fidelity="verification" if fidelity == "verification" else "screening",
                           metrics=score.metrics, mesh=mesh, validity=validity, solver_version="mock",
                           elapsed_ms=score.eval_ms)
    return score, art


def convergence_check(m: ProjectManifest, params: Mapping[str, ParamValue], geometry: str) -> CheckResult:
    return CheckResult(id="mesh_convergence", passed=True, actual=1.8, limit=3.0,
                       detail="mock: hole stress changed 1.8 % between refinement levels (limit 3 %)")


__all__ = ["ADAPTER_ID", "VERSION", "BRACKET_SPACE", "CATALOG", "capability", "metric_catalog",
           "validate_manifest", "metrics", "evaluate", "convergence_check"]

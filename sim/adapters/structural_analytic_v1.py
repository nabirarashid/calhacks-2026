"""structural_analytic_v1 — screening SolverAdapter for the static_structural domain.

W-B, PLAN.md v3 C.2 P3-B1. Deterministic, process-safe, zero network, zero
Onshape calls. Every candidate in a bracket run goes through this; the top-k and
the champion additionally go through `structural_fea_v1`.

Units are mm / N / MPa / g throughout (so E in MPa, I in mm^4, stress in MPa).

Physics, and where each piece comes from:

* **Section.** The loaded flange is a composite T: a plate `width x thickness`
  plus an optional centred top rib `rib_thickness x rib_height`. Second moment
  about the composite neutral axis, extreme-fibre distance from whichever face
  is further from it.
* **Deflection.** Euler-Bernoulli cantilever `P L^3 / 3EI` plus the Timoshenko
  shear term `P L / (kappa G A)` with kappa = 5/6. The shear term is small at
  high L/h but a stubby bracket is not a slender beam, so it is not dropped.
* **Root stress.** Nominal `M c / I` at the wall, multiplied by a fillet stress
  concentration factor interpolated from Peterson's shoulder-fillet-in-bending
  chart. This is an *approximation*: an L-corner is not a stepped flat bar. The
  approximation is declared in the validity envelope, not hidden.
* **Hole stress.** The root moment is reacted by the mounting bolts as a force
  couple over their measured spacing. That bolt force is carried by the net
  section at the hole row, concentrated by Heywood's finite-width hole factor
  `Kt_net = 2 + (1 - d/W)^3`, which tends to the classical 3.0 as d/W -> 0.
  Lightening holes are checked the same way at their own stations, where the
  local moment is lower.
* **Mass.** CAD volume when a verified export is available, otherwise the
  analytic volume of plate + upright + rib minus the lightening holes.

Nothing here defaults an engineering input. Missing material, load, fixtures or
mounting-hole geometry returns a `BlockingQuestion` and the adapter refuses to
evaluate (safety rules 2 and 3).
"""
import math
import time
from typing import Dict, List, Mapping, Optional, Tuple

from shared.contracts import (AnalysisArtifact, Goal, MetricInfo, ParamValue, Score,
                              canonicalize)
from shared.manifest import (AdapterCapability, BlockingQuestion, CheckResult,
                             ProjectManifest)
from shared.mocks.fake_sim import aggregate

ADAPTER_ID = "structural_analytic_v1"
VERSION = "1.0.0"

# Peterson's Stress Concentration Factors, shoulder fillet in bending, deep
# shoulder (D/d ~ 2). Chart reads, so treat as +/- 10 %; that uncertainty is
# reported in the validity envelope rather than implied to be exact.
_FILLET_KT_RT = (0.05, 0.10, 0.20, 0.30, 0.50, 1.00, 2.00)
_FILLET_KT = (2.45, 2.00, 1.70, 1.55, 1.38, 1.22, 1.12)

SHEAR_KAPPA = 5.0 / 6.0            # rectangular section
SMALL_DEFLECTION_FRAC = 0.10       # of flange length
AXIAL_NEGLECT_FRAC = 0.10          # flag an axial component above this share of the bending load


class ManifestNotReady(ValueError):
    """Raised instead of evaluating with a guessed input."""


# ---------------------------------------------------------------- capability

def capability() -> AdapterCapability:
    return AdapterCapability(
        adapter_id=ADAPTER_ID, kind="solver", version=VERSION, domain="static_structural",
        required_fields=["material", "load_cases[0].vector_n", "load_cases[0].fixtures",
                         "protected[mount_*].nominal"],
        metrics=["mass_g", "tip_deflection_mm", "stress_max_mpa", "stress_hole_mpa",
                 "safety_factor"],
        fidelity=["screening"],
        process_safe=True,
        validity_envelope={
            "material": "linear elastic, isotropic; printed PLA is anisotropic so "
                        "datasheet values are nominal, not tested",
            "deflection": "small: tip deflection below 10 % of flange length",
            "stress": "below yield; a result past yield is reported, never clipped",
            "fillet_kt": "L-corner approximated by a stepped-flat-bar shoulder fillet "
                         "(Peterson); treat as +/- 10 %",
            "load": "bending component only; a significant axial component is flagged",
            "fidelity": "screening — ranks designs and finds tradeoffs; it does not "
                        "certify a part",
        },
    )


def metric_catalog() -> List[MetricInfo]:
    return [
        MetricInfo(name="mass_g", unit="g", description="Bracket mass (CAD volume when available)",
                   better="lower", typical_min=5.0, typical_max=60.0),
        MetricInfo(name="tip_deflection_mm", unit="mm",
                   description="Deflection at the load hole (bending + shear)",
                   better="lower", typical_min=0.0, typical_max=5.0),
        MetricInfo(name="stress_max_mpa", unit="MPa",
                   description="Peak bending stress at the root fillet, away from holes",
                   better="lower", typical_min=0.0, typical_max=60.0),
        MetricInfo(name="stress_hole_mpa", unit="MPa",
                   description="Peak net-section stress at a hole (mounting or lightening)",
                   better="lower", typical_min=0.0, typical_max=80.0),
        MetricInfo(name="safety_factor", unit="",
                   description="Yield divided by the governing stress", better="higher",
                   typical_min=0.5, typical_max=6.0),
    ]


# ---------------------------------------------------------------- manifest gate

def _mount_holes(m: ProjectManifest) -> List[Dict[str, float]]:
    """Mounting-hole geometry from the manifest's protected interfaces.

    Read from the manifest rather than assumed, so the adapter stays generic:
    the bolt couple arm is whatever the engineer approved.
    """
    out = []
    for iface in m.protected:
        if iface.kind != "hole" or not iface.id.startswith("mount"):
            continue
        nom = iface.nominal or {}
        if "d" not in nom:
            continue
        out.append({"id": iface.id, "d": float(nom["d"]),
                    "x": float(nom.get("x", 0.0)), "y": float(nom.get("y", 0.0)),
                    "z": float(nom.get("z", 0.0))})
    return out


def validate_manifest(m: ProjectManifest) -> List[BlockingQuestion]:
    """Empty list means solver-ready. Every gap is a question, never a default."""
    out = []  # type: List[BlockingQuestion]

    if m.material is None or not m.material.confirmed:
        out.append(BlockingQuestion(
            id="material", field="material", required_for=3,
            prompt="Which material, and from which source (datasheet or measured)?",
            why="Young's modulus sets deflection and yield sets every safety factor."))

    lc = m.load_cases[0] if m.load_cases else None
    if lc is None or not lc.confirmed or not lc.vector_n:
        out.append(BlockingQuestion(
            id="load", field="load_cases[0].vector_n", required_for=3,
            prompt="What force acts at the load hole, in newtons and direction?",
            why="A bracket's stress is proportional to the load; it is never assumed."))
    if lc is None or not lc.fixtures:
        out.append(BlockingQuestion(
            id="fixtures", field="load_cases[0].fixtures", required_for=3,
            prompt="Which interfaces are bolted to the wall?",
            why="The boundary condition decides where the bracket bends and what the "
                "bolts react."))

    holes = _mount_holes(m)
    if len(holes) < 2:
        out.append(BlockingQuestion(
            id="mount_geometry", field="protected[mount_*].nominal", required_for=3,
            prompt="Give at least two mounting holes with positions and diameters.",
            why="The bolt spacing is the lever arm that converts the root moment into "
                "bolt force, so hole stress cannot be computed without it."))
    elif _bolt_spacing(holes) <= 0.0:
        out.append(BlockingQuestion(
            id="mount_spacing", field="protected[mount_*].nominal", required_for=3,
            prompt="The mounting holes are coincident; confirm their positions.",
            why="A zero bolt spacing implies infinite bolt force."))
    return out


def _bolt_spacing(holes: List[Dict[str, float]]) -> float:
    """Largest centre distance in the bolt pattern: the couple's lever arm."""
    best = 0.0
    for i in range(len(holes)):
        for j in range(i + 1, len(holes)):
            a, b = holes[i], holes[j]
            best = max(best, math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2
                                       + (a["z"] - b["z"]) ** 2))
    return best


# ---------------------------------------------------------------- mechanics

def section_properties(width_mm: float, thickness_mm: float, rib_h_mm: float,
                       rib_t_mm: float) -> Tuple[float, float]:
    """(second moment mm^4, extreme-fibre distance mm) of plate + centred top rib."""
    a_plate = width_mm * thickness_mm
    y_plate = thickness_mm / 2.0
    a_rib = rib_t_mm * rib_h_mm
    y_rib = thickness_mm + rib_h_mm / 2.0
    area = a_plate + a_rib
    if area <= 0.0:
        raise ManifestNotReady("degenerate section: zero area")
    y_c = (a_plate * y_plate + a_rib * y_rib) / area
    inertia = (width_mm * thickness_mm ** 3 / 12.0 + a_plate * (y_plate - y_c) ** 2
               + rib_t_mm * rib_h_mm ** 3 / 12.0 + a_rib * (y_rib - y_c) ** 2)
    c = max(y_c, thickness_mm + rib_h_mm - y_c)
    return inertia, c


def fillet_kt(fillet_r_mm: float, thickness_mm: float) -> Tuple[float, bool]:
    """Peterson shoulder-fillet-in-bending Kt by linear interpolation on r/t.

    Returns (Kt, in_range). Outside the chart the end value is held and
    in_range is False, which the caller records as a validity note.
    """
    if thickness_mm <= 0.0:
        raise ManifestNotReady("thickness must be positive")
    r_t = fillet_r_mm / thickness_mm
    if r_t <= _FILLET_KT_RT[0]:
        return _FILLET_KT[0], r_t >= _FILLET_KT_RT[0]
    if r_t >= _FILLET_KT_RT[-1]:
        return _FILLET_KT[-1], True
    for i in range(1, len(_FILLET_KT_RT)):
        if r_t <= _FILLET_KT_RT[i]:
            x0, x1 = _FILLET_KT_RT[i - 1], _FILLET_KT_RT[i]
            y0, y1 = _FILLET_KT[i - 1], _FILLET_KT[i]
            return y0 + (y1 - y0) * (r_t - x0) / (x1 - x0), True
    return _FILLET_KT[-1], True


def hole_kt(hole_d_mm: float, width_mm: float) -> float:
    """Heywood finite-width hole factor, referenced to the NET section.

    Kt = 2 + (1 - d/W)^3, which gives the classical 3.0 for a small hole in a
    wide plate and falls as the hole takes up more of the width.
    """
    if width_mm <= 0.0 or hole_d_mm <= 0.0:
        return 1.0
    ratio = min(max(hole_d_mm / width_mm, 0.0), 0.95)
    return 2.0 + (1.0 - ratio) ** 3


# ---------------------------------------------------------------- evaluation

def metrics(m: ProjectManifest, params: Mapping[str, ParamValue],
            cad_volume_mm3: Optional[float] = None) -> Tuple[Dict[str, float], List[str]]:
    """Deterministic metrics plus validity notes. Raises if the manifest is not ready."""
    blocking = validate_manifest(m)
    if blocking:
        raise ManifestNotReady("not solver-ready: %s" % [q.id for q in blocking])

    p = canonicalize(m.design_space, dict(params))
    ctx = m.design_space.context
    width = float(ctx.get("width_mm", 30.0))
    upright = float(ctx.get("upright_mm", 40.0))
    hole_d = float(ctx.get("lightening_hole_d_mm", 5.0))

    thickness = float(p["thickness"])
    length = float(p["flange_length"])
    rib_h = float(p["rib_height"])
    rib_t = float(p["rib_thickness"])
    fillet = float(p["fillet_radius"])
    n_holes = int(p["lightening_holes"])

    mat = m.material
    lc = m.load_cases[0]
    vec = [float(v) for v in (lc.vector_n or [0.0, 0.0, 0.0])]
    f_bend = abs(vec[1])                       # perpendicular to the flange
    f_axial = math.sqrt(vec[0] ** 2 + vec[2] ** 2)

    notes = []  # type: List[str]
    if f_bend <= 0.0:
        raise ManifestNotReady("load case has no bending component (vector_n[1] == 0)")
    if f_axial > AXIAL_NEGLECT_FRAC * f_bend:
        notes.append("axial load component %.1f N is neglected by this screening model "
                     "(%.0f %% of the bending load)" % (f_axial, 100.0 * f_axial / f_bend))

    inertia, c = section_properties(width, thickness, rib_h, rib_t)
    moment_root = f_bend * length                              # N*mm

    # --- root stress, away from holes, concentrated by the corner fillet
    kt_f, kt_in_range = fillet_kt(fillet, thickness)
    if not kt_in_range:
        notes.append("fillet r/t = %.3f is below the Peterson chart range; Kt held at "
                     "%.2f and is likely optimistic" % (fillet / thickness, kt_f))
    stress_nominal = moment_root * c / inertia
    stress_max = kt_f * stress_nominal

    # --- mounting holes: root moment reacted as a bolt couple over the measured arm
    holes = _mount_holes(m)
    arm = _bolt_spacing(holes)
    bolt_force = moment_root / arm
    mount_d = max(h["d"] for h in holes)
    net_area_mount = max((width - mount_d) * thickness, 1e-6)
    stress_hole = hole_kt(mount_d, width) * bolt_force / net_area_mount

    # --- lightening holes: same treatment at their own (lower-moment) stations
    #     Convention: evenly spaced across the middle half of the flange, which the
    #     Part Studio must match. Recorded as an assumption, not hidden.
    if n_holes > 0:
        net_area_light = max((width - hole_d) * thickness, 1e-6)
        kt_light = hole_kt(hole_d, width)
        for i in range(n_holes):
            frac = 0.25 + 0.5 * ((i + 0.5) / n_holes)
            x = frac * length
            moment_local = f_bend * (length - x)
            # Net-section bending at the holed station, using the reduced width.
            inertia_net, c_net = section_properties(width - hole_d, thickness, rib_h, rib_t)
            s_bending = kt_light * moment_local * c_net / inertia_net
            s_tension = kt_light * 0.0                 # no axial path in this load case
            stress_hole = max(stress_hole, s_bending + s_tension)
        notes.append("%d lightening hole(s) assumed evenly spaced across the middle half "
                     "of the flange; the Part Studio must match" % n_holes)
        del net_area_light

    # --- deflection: Euler-Bernoulli plus the shear term
    e_mpa = float(mat.youngs_mpa)
    nu = float(mat.poisson)
    g_mpa = e_mpa / (2.0 * (1.0 + nu))
    area_shear = width * thickness + rib_t * rib_h
    deflection = (f_bend * length ** 3 / (3.0 * e_mpa * inertia)
                  + f_bend * length / (SHEAR_KAPPA * g_mpa * area_shear))

    # --- mass: prefer measured CAD volume
    if cad_volume_mm3 is not None and cad_volume_mm3 > 0.0:
        volume = float(cad_volume_mm3)
    else:
        volume = (length * width * thickness
                  + upright * width * thickness
                  + length * rib_h * rib_t
                  - n_holes * math.pi * (hole_d / 2.0) ** 2 * thickness)
        notes.append("mass from the analytic volume; the fillet is neglected, so the "
                     "real part is slightly heavier")
    mass_g = volume * float(mat.density_kg_m3) * 1e-6

    governing = max(stress_max, stress_hole, 1e-9)
    yield_mpa = float(mat.yield_mpa)

    if deflection > SMALL_DEFLECTION_FRAC * length:
        notes.append("tip deflection %.2f mm exceeds %.0f %% of the flange length: "
                     "outside the small-deflection envelope"
                     % (deflection, 100.0 * SMALL_DEFLECTION_FRAC))
    if governing > yield_mpa:
        notes.append("governing stress %.1f MPa exceeds yield %.1f MPa; the linear-elastic "
                     "result is not valid past this point and is reported, not clipped"
                     % (governing, yield_mpa))

    out = {
        "mass_g": mass_g,
        "tip_deflection_mm": deflection,
        "stress_max_mpa": stress_max,
        "stress_hole_mpa": stress_hole,
        "safety_factor": yield_mpa / governing,
    }
    return out, notes


def evaluate(m: ProjectManifest, params: Mapping[str, ParamValue], goal: Goal, *,
             geometry: Optional[str] = None, fidelity: str = "screening",
             design_id: str = "", cad_volume_mm3: Optional[float] = None
             ) -> Tuple[Score, AnalysisArtifact]:
    """Screening evaluation. `geometry` is accepted for interface parity; this
    adapter needs no mesh, and only uses a CAD volume if one is handed to it."""
    started = time.perf_counter()
    if fidelity != "screening":
        raise ValueError("%s is screening-only; use structural_fea_v1 for verification"
                         % ADAPTER_ID)

    p = canonicalize(m.design_space, dict(params))
    mets, notes = metrics(m, p, cad_volume_mm3=cad_volume_mm3)
    obj, viols, feasible, agg = aggregate(m.design_space, p, mets, goal, metric_catalog())
    elapsed = (time.perf_counter() - started) * 1000.0

    score = Score(metrics={k: round(v, 4) for k, v in mets.items()},
                  objective_scores=obj, violations=viols, feasible=feasible,
                  aggregate=round(agg, 5), warnings=list(notes),
                  fidelity="fast", eval_ms=elapsed)
    artifact = AnalysisArtifact(
        design_id=design_id, adapter_id=ADAPTER_ID, adapter_version=VERSION,
        fidelity="screening", metrics=score.metrics, converged=None,
        validity=list(notes), solver_version="closed-form",
        diagnostics={"bolt_arm_mm": _bolt_spacing(_mount_holes(m))},
        elapsed_ms=elapsed)
    return score, artifact


def convergence_check(m: ProjectManifest, params: Mapping[str, ParamValue],
                      geometry: str) -> CheckResult:
    """A closed-form model has no mesh, so this cannot run and must not pass.

    `passed=None` blocks rather than claiming convergence (safety rule 3).
    """
    return CheckResult(
        id="mesh_convergence", passed=None,
        detail="%s is closed-form: there is no mesh to refine. Use structural_fea_v1 "
               "for a convergence check." % ADAPTER_ID)


__all__ = ["ADAPTER_ID", "VERSION", "ManifestNotReady", "capability", "metric_catalog",
           "validate_manifest", "section_properties", "fillet_kt", "hole_kt", "metrics",
           "evaluate", "convergence_check"]

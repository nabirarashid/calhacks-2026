"""rear_wing_v1 — race-car rear wing scorer (W-B, PLAN.md v4 B.5 / W-B B2).

Deterministic, process-safe, no network. One fast evaluation is ~20 ms.

The wing is solved as a lifting wing at positive angle of attack and reported as
downforce. With no ground effect modelled an inverted wing is the mirror image of
an upright one, so this is exact within the model.

Every quantity has one source, and each was checked before it was used:

* **Lift: vortex-lattice (VLM)** on one full-chord lattice whose airfoil already
  has the flap deflected (``Airfoil.add_control_surface``), so VLM's camber line
  is the real NACA 4412 line with the aft portion rotated about the hinge. At
  flap 0 it reproduces a plain NACA 4412 exactly; against Helmbold's
  low-aspect-ratio lifting-line slope it is within ~4 % at the fast resolution,
  and the flap increment tracks Glauert thin-airfoil flap theory within 2-4 % up
  to 20 deg.
  AeroSandbox's AeroBuildup was the plan's fast path and was rejected for lift:
  its slope is right but it does not reduce *camber* lift for a finite wing, so
  on this AR-3 wing it over-predicts CL by 27-74 % (worst at low AoA, where it
  reports nearly the 2D section value). A flap is extra camber, so the same
  error inflated flap effectiveness by ~50 % at small flap angles.
* **Span efficiency: Prandtl lifting-line theory** (Glauert's Fourier solution)
  for the planform's aspect ratio. Not taken from VLM, whose near-field induced
  drag implies e = 1.04, above the planar maximum of 1 (Munk).
* **Endplates: Hoerner's effective aspect ratio**, ``AR_eff = AR (1 + 1.9 h/b)``,
  applied in both places endplates act: the lift slope rises with AR, and
  induced drag is ``CL^2 / (pi e AR_eff)`` (Anderson, *Fundamentals of
  Aerodynamics*, ch. 5).
* **Profile drag and stall: NeuralFoil**, on the NACA 4412 section with the flap
  deflected, at the run's Reynolds number. Profile drag is read at the effective
  angle (AoA minus the induced angle). Stall is the section CL peak.
* **Viscous lift correction: NeuralFoil.** VLM is inviscid, so it never stalls
  and never sees the flap's boundary layer separate. Its 3D lift is scaled by the
  section's viscous/inviscid lift ratio at the effective angle (NeuralFoil over
  Glauert thin-airfoil flap theory). Measured on this section, that ratio is
  ~1.0 up to 10 deg of flap and falls to 0.79 at 20 deg and 0.58-0.64 at 30 deg,
  where the plain flap saturates near CL 1.6-1.8. Without it VLM over-predicts
  flap lift by 25-75 %. The same ratio handles stall smoothly. It is capped at
  1.0: the correction only removes lift, never adds it.
* **Endplate skin friction**: two plates, both faces, turbulent flat-plate
  ``Cf = 0.074 Re^-0.2``. Small but real, so endplate height is not free.

``hifi`` runs the identical model at a converged VLM resolution, so the
high-fidelity check is a genuine mesh-refinement check.

Validity envelope: incompressible, no ground effect, steady, flap slot not
modelled (plain flap, so maximum downforce is conservative), linear lifting-line
corrections reliable below stall.
"""
import math
import warnings as python_warnings
from typing import Dict, List, Mapping, Optional, Tuple

from shared.contracts import DesignSpace, Goal, MetricInfo, ParamValue
from sim.plugins import PluginEvaluation, ScorerPlugin

SCORER_ID = "rear_wing_v1"
VERSION = "1.0.0"
process_safe = True                 # importable by id, so spawned workers can rebuild it

AIRFOIL = "naca4412"
DEFAULT_VELOCITY_MPS = 25.0
DEFAULT_RHO = 1.225
MU_AIR = 1.789e-5                   # Pa s, sea-level standard atmosphere
THIN_AIRFOIL_SLOPE = 2.0 * math.pi  # per rad, thin-airfoil theory
HOERNER_K = 1.9                     # AR_eff = AR (1 + 1.9 h / b)
STALL_SWEEP_DEG = (-4.0, 24.0, 57)  # NeuralFoil alpha sweep for the CL peak
VLM_FAST = (12, 6)                  # span x chord panels: 15 ms, within 1.7 % of converged
VLM_HIFI = (24, 12)                 # converged reference for the refinement check
GLAUERT_STATIONS = 24
ALPHA_L0_NACA4412_DEG = -4.0       # Abbott & von Doenhoff, *Theory of Wing Sections*
VISCOUS_ITERATIONS = 4              # fixed point: CL -> induced angle -> viscous ratio -> CL

_ASB = None


def _asb():
    """Import AeroSandbox once, quietly (matplotlib warns on import)."""
    global _ASB
    if _ASB is None:
        with python_warnings.catch_warnings():
            python_warnings.simplefilter("ignore")
            import aerosandbox as asb
        _ASB = asb
    return _ASB


# ------------------------------------------------------------------ catalog

def _catalog() -> List[MetricInfo]:
    # typical_min/max are aggregation normalisation ranges, calibrated from a
    # 300-sample Latin hypercube over the frozen B.5 box (p2..p98, rounded out).
    # A range that overshoots the real spread compresses the score; one that
    # undershoots saturates it. Either way the agent loses its gradient.
    #   downforce_n  p2 39.9  p98 146   max 157
    #   drag_n       p2 2.5   p98 38.5  max 62.8
    #   l_over_d     p2 1.4   p98 16.5  max 18.3
    return [
        MetricInfo(name="downforce_n", unit="N", better="higher",
                   description="Downforce at the design speed (VLM + viscous correction + endplates)",
                   typical_min=40.0, typical_max=160.0),
        MetricInfo(name="drag_n", unit="N", better="lower",
                   description="Total drag: induced + section profile + endplate friction",
                   typical_min=2.0, typical_max=45.0),
        MetricInfo(name="l_over_d", unit="", better="higher",
                   description="Downforce divided by drag",
                   typical_min=1.0, typical_max=18.0),
        MetricInfo(name="drag_induced_n", unit="N", better="info",
                   description="Induced drag, CL^2 / (pi e AR_eff)",
                   typical_min=0.0, typical_max=18.0),
        MetricInfo(name="drag_profile_n", unit="N", better="info",
                   description="Section profile drag (NeuralFoil) plus endplate skin friction",
                   typical_min=0.0, typical_max=60.0),
        MetricInfo(name="cl", unit="", better="info",
                   description="Wing lift coefficient on planform area",
                   typical_min=0.3, typical_max=1.4),
        MetricInfo(name="stall_margin_deg", unit="deg", better="higher",
                   description="Section stall angle minus angle of attack (negative = stalled)",
                   typical_min=-10.0, typical_max=13.0),
        MetricInfo(name="span_efficiency", unit="", better="info",
                   description="Oswald e from Prandtl lifting-line theory for the planform",
                   typical_min=0.95, typical_max=1.0),
        MetricInfo(name="aspect_ratio_eff", unit="", better="info",
                   description="Hoerner endplate-corrected aspect ratio",
                   typical_min=3.0, typical_max=8.0),
        MetricInfo(name="reynolds", unit="", better="info",
                   description="Chord Reynolds number",
                   typical_min=3.0e5, typical_max=6.5e5),
    ]


# ------------------------------------------------------------------ physics

def hoerner_ar_eff(aspect_ratio: float, endplate_h_m: float, span_m: float) -> float:
    """Effective aspect ratio of a wing with endplates of height h (Hoerner)."""
    if span_m <= 0.0:
        raise ValueError("span must be positive")
    return aspect_ratio * (1.0 + HOERNER_K * endplate_h_m / span_m)


def lift_slope_factor(aspect_ratio: float, e: float,
                      a0: float = THIN_AIRFOIL_SLOPE) -> float:
    """Finite-wing lift-slope reduction 1 / (1 + a0 / (pi e AR))."""
    return 1.0 / (1.0 + a0 / (math.pi * e * aspect_ratio))


def flat_plate_cf_turbulent(reynolds: float) -> float:
    """Turbulent flat-plate skin friction, Cf = 0.074 Re^-0.2."""
    return 0.074 * reynolds ** -0.2


def section_stall_deg(chord_m: float, flap_deg: float, flap_frac: float,
                      velocity: float, rho: float) -> float:
    """Angle of the NeuralFoil CL peak for the flapped section."""
    import numpy as np

    asb = _asb()
    re = rho * velocity * chord_m / MU_AIR
    foil = asb.Airfoil(AIRFOIL).add_control_surface(
        deflection=flap_deg, hinge_point_x=1.0 - flap_frac)
    lo, hi, n = STALL_SWEEP_DEG
    alphas = np.linspace(lo, hi, n)
    cl = np.asarray(foil.get_aero_from_neuralfoil(alpha=alphas, Re=re)["CL"]).ravel()
    return float(alphas[int(np.argmax(cl))])


def _scalar(value) -> float:
    # Always ravel: float() on a 1-element array is deprecated in NumPy >= 1.25
    # and is scheduled to become an error.
    import numpy as np
    return float(np.asarray(value, dtype=float).ravel()[0])


def glauert_span_efficiency(aspect_ratio: float, a0: float = THIN_AIRFOIL_SLOPE,
                            stations: int = GLAUERT_STATIONS) -> float:
    """Oswald e of an untwisted rectangular wing from Prandtl lifting-line theory.

    Solves Glauert's monoplane equation for the odd Fourier coefficients and
    returns e = 1 / (1 + delta), delta = sum_{n>=3} n (A_n / A_1)^2. For an
    untwisted planform delta depends only on aspect ratio, not on AoA.
    """
    import numpy as np

    if aspect_ratio <= 0.0:
        raise ValueError("aspect ratio must be positive")
    n_terms = stations
    orders = np.arange(1, 2 * n_terms, 2)                       # odd n
    theta = np.linspace(0.0, np.pi / 2.0, n_terms + 2)[1:-1]     # half-span stations
    theta = theta[:n_terms] if theta.size >= n_terms else theta
    orders = orders[:theta.size]
    mu = a0 / (4.0 * aspect_ratio)                               # a0 c / (4 b), c/b = 1/AR
    lhs = np.sin(np.outer(theta, orders)) * (mu * orders[None, :] + np.sin(theta)[:, None])
    rhs = mu * np.sin(theta)                                     # unit (alpha - alpha_L0)
    coeffs = np.linalg.solve(lhs, rhs)
    delta = float(np.sum(orders[1:] * (coeffs[1:] / coeffs[0]) ** 2))
    return 1.0 / (1.0 + delta)


def _vlm_cl(span_m: float, chord_m: float, flap_deg: float, flap_frac: float,
            aoa_deg: float, velocity: float, resolution: Tuple[int, int]) -> float:
    asb = _asb()
    with python_warnings.catch_warnings():
        python_warnings.simplefilter("ignore")
        res = asb.VortexLatticeMethod(
            airplane=_vlm_airplane(span_m, chord_m, flap_deg, flap_frac),
            op_point=asb.OperatingPoint(velocity=velocity, alpha=aoa_deg),
            spanwise_resolution=resolution[0], chordwise_resolution=resolution[1]).run()
    return _scalar(res["CL"])


def glauert_flap_slope(flap_frac: float) -> float:
    """Thin-airfoil flap effectiveness dCL/d(delta), per rad (Glauert).

    Hinge at x_h = (1 - E) c, theta_h = arccos(2E - 1),
    dCL/d(delta) = 2 (pi - theta_h + sin theta_h).
    """
    theta_h = math.acos(2.0 * flap_frac - 1.0)
    return 2.0 * (math.pi - theta_h + math.sin(theta_h))


def inviscid_section_cl(alpha_deg: float, flap_deg: float, flap_frac: float) -> float:
    """Thin-airfoil CL of the flapped NACA 4412: 2 pi (alpha - alpha_L0) + flap term."""
    return (THIN_AIRFOIL_SLOPE * math.radians(alpha_deg - ALPHA_L0_NACA4412_DEG)
            + glauert_flap_slope(flap_frac) * math.radians(flap_deg))


def _section_aero(chord_m: float, flap_deg: float, flap_frac: float, alpha_deg: float,
                  reynolds: float) -> Tuple[float, float]:
    """NeuralFoil (CL, CD) of the flapped section."""
    foil = _asb().Airfoil(AIRFOIL).add_control_surface(
        deflection=flap_deg, hinge_point_x=1.0 - flap_frac)
    aero = foil.get_aero_from_neuralfoil(alpha=alpha_deg, Re=reynolds)
    return _scalar(aero["CL"]), _scalar(aero["CD"])


def solve(params: Mapping[str, ParamValue], velocity: float = DEFAULT_VELOCITY_MPS,
          rho: float = DEFAULT_RHO, high_fidelity: bool = False
          ) -> Tuple[Dict[str, float], List[str], Dict[str, float]]:
    """Every rear_wing_v1 metric, plus validity notes and diagnostics."""
    aoa = float(params["aoa_deg"])
    span = float(params["span_mm"]) / 1000.0
    chord = float(params["chord_mm"]) / 1000.0
    flap = float(params["flap_angle_deg"])
    frac = float(params["flap_chord_frac"])
    endplate = float(params["endplate_height_mm"]) / 1000.0
    if span <= 0.0 or chord <= 0.0 or velocity <= 0.0 or rho <= 0.0:
        raise ValueError("span, chord, velocity and density must be positive")

    q = 0.5 * rho * velocity ** 2
    area = span * chord
    reynolds = rho * velocity * chord / MU_AIR
    notes = []  # type: List[str]
    resolution = VLM_HIFI if high_fidelity else VLM_FAST

    ar = span / chord
    ar_eff = hoerner_ar_eff(ar, endplate, span)
    e = glauert_span_efficiency(ar)
    k_lift = lift_slope_factor(ar_eff, e) / lift_slope_factor(ar, e)

    stall = section_stall_deg(chord, flap, frac, velocity, rho)
    margin = stall - aoa
    if margin < 0.0:
        notes.append("section stalled (margin %.1f deg); lift is from the viscous-corrected "
                     "post-stall section and the design is infeasible to the loop" % margin)

    cl_geo = _vlm_cl(span, chord, flap, frac, aoa, velocity, resolution)
    cl_inviscid = cl_geo * k_lift

    # Fixed point: the viscous ratio depends on the effective angle, which depends
    # on CL through the induced angle. Converges in a few passes (monotone).
    cl = cl_inviscid
    k_visc = 1.0
    alpha_eff = aoa
    cd_sec = 0.0
    for _ in range(VISCOUS_ITERATIONS):
        alpha_eff = aoa - math.degrees(cl / (math.pi * e * ar_eff))
        cl_nf, cd_sec = _section_aero(chord, flap, frac, alpha_eff, reynolds)
        cl_inv_2d = inviscid_section_cl(alpha_eff, flap, frac)
        k_visc = min(cl_nf / cl_inv_2d, 1.0) if cl_inv_2d > 1e-6 else 1.0
        cl = cl_inviscid * k_visc
    alpha_induced = aoa - alpha_eff

    cdi = cl ** 2 / (math.pi * e * ar_eff)
    d_ind = cdi * q * area
    d_endplate = q * flat_plate_cf_turbulent(reynolds) * 4.0 * endplate * chord
    d_prof = cd_sec * q * area + d_endplate

    downforce = cl * q * area
    drag = d_ind + d_prof

    metrics = {
        "downforce_n": downforce,
        "drag_n": drag,
        "l_over_d": downforce / drag if drag > 0.0 else 0.0,
        "drag_induced_n": d_ind,
        "drag_profile_n": d_prof,
        "cl": cl,
        "stall_margin_deg": margin,
        "span_efficiency": e,
        "aspect_ratio_eff": ar_eff,
        "reynolds": reynolds,
    }
    diagnostics = {
        "aspect_ratio_geo": ar,
        "lift_endplate_factor": k_lift,
        "cl_vlm_geo": cl_geo,
        "cl_inviscid": cl_inviscid,
        "viscous_factor": k_visc,
        "alpha_induced_deg": alpha_induced,
        "alpha_eff_deg": alpha_eff,
        "cd_section": cd_sec,
        "drag_endplate_n": d_endplate,
        "stall_angle_deg": stall,
        "q_pa": q,
        "vlm_span_panels": float(resolution[0]),
        "vlm_chord_panels": float(resolution[1]),
    }
    if high_fidelity:
        fast_cl = _vlm_cl(span, chord, flap, frac, aoa, velocity, VLM_FAST) * k_lift * k_visc
        diagnostics["fast_cl"] = fast_cl
        diagnostics["refinement_change_pct"] = 100.0 * (fast_cl - cl) / cl if cl else 0.0
    return metrics, notes, diagnostics


def _vlm_airplane(span_m: float, chord_m: float, flap_deg: float, flap_frac: float):
    """One full-chord lattice; the flap is deflected in the airfoil's own geometry.

    Two things were measured before settling on this:

    * AeroSandbox 4.2.8's VortexLatticeMethod **ignores ``WingXSec`` ControlSurface
      deflection**: CL is identical (0.5784) at 0, 15 and 30 deg of flap.
    * Splitting main element and flap into two lattices, each with its own NACA
      4412 camber, gives a double-humped section rather than a 4412: at flap 0 it
      under-predicts lift by 25 % against theory.

    Deflecting the flap inside the airfoil coordinates avoids both: VLM meshes the
    true 4412 camber line with its aft part rotated about the hinge.
    """
    asb = _asb()
    foil = asb.Airfoil(AIRFOIL).add_control_surface(
        deflection=flap_deg, hinge_point_x=1.0 - flap_frac)
    wing = asb.Wing(name="rear_wing", symmetric=True, xsecs=[
        asb.WingXSec(xyz_le=[0.0, 0.0, 0.0], chord=chord_m, airfoil=foil),
        asb.WingXSec(xyz_le=[0.0, span_m / 2.0, 0.0], chord=chord_m, airfoil=foil),
    ])
    return asb.Airplane(name="rear_wing_vlm", wings=[wing], s_ref=span_m * chord_m,
                        c_ref=chord_m, b_ref=span_m)

# ------------------------------------------------------------------ plugin

class RearWingV1Scorer(object):
    scorer_id = SCORER_ID
    process_safe = True

    def metric_catalog(self) -> List[MetricInfo]:
        return [m.model_copy() for m in _catalog()]

    @staticmethod
    def _context(space: DesignSpace, goal: Optional[Goal]) -> Tuple[float, float]:
        ctx = dict(space.context)
        if goal is not None:
            ctx.update(goal.context_overrides)
        velocity = float(ctx.get("velocity_mps", DEFAULT_VELOCITY_MPS))
        rho = float(ctx.get("rho", DEFAULT_RHO))
        return velocity, rho

    def evaluate_metrics(self, space: DesignSpace, params: Mapping[str, ParamValue],
                         goal: Optional[Goal] = None,
                         fidelity: str = "fast") -> PluginEvaluation:
        if space.scorer != self.scorer_id:
            raise ValueError("RearWingV1Scorer cannot score design space %r with scorer %r"
                             % (space.id, space.scorer))
        if fidelity not in ("fast", "high"):
            raise ValueError("fidelity must be 'fast' or 'high'")
        velocity, rho = self._context(space, goal)
        metrics, notes, diagnostics = solve(params, velocity, rho,
                                            high_fidelity=fidelity == "high")
        warnings = list(notes)
        if not 0.0 < metrics["l_over_d"] < 40.0:
            warnings.append("L/D %.2f is outside (0, 40)" % metrics["l_over_d"])
        if not 1.0e5 <= metrics["reynolds"] <= 1.0e6:
            warnings.append("Reynolds %.2e is outside NeuralFoil's comfortable range "
                            "for this section" % metrics["reynolds"])
        if fidelity == "high" and abs(diagnostics.get("refinement_change_pct", 0.0)) > 3.0:
            warnings.append("VLM refinement changed CL by %.1f %% (limit 3 %%): the fast "
                            "resolution is not converged for this design"
                            % diagnostics["refinement_change_pct"])
        return PluginEvaluation(metrics=metrics, warnings=warnings, diagnostics=diagnostics)

    def metrics(self, space: DesignSpace, params: Mapping[str, ParamValue],
                goal: Optional[Goal] = None) -> Dict[str, float]:
        return self.evaluate_metrics(space, params, goal).metrics

    def hifi(self, space: DesignSpace, params: Mapping[str, ParamValue],
             goal: Optional[Goal] = None) -> PluginEvaluation:
        return self.evaluate_metrics(space, params, goal, fidelity="high")


PLUGIN = RearWingV1Scorer()  # type: ScorerPlugin


def get_plugin() -> ScorerPlugin:
    return PLUGIN


def metric_catalog() -> List[MetricInfo]:
    return PLUGIN.metric_catalog()


__all__ = ["SCORER_ID", "VERSION", "PLUGIN", "RearWingV1Scorer", "get_plugin",
           "metric_catalog", "solve", "hoerner_ar_eff", "lift_slope_factor",
           "flat_plate_cf_turbulent", "section_stall_deg",
           "glauert_span_efficiency", "glauert_flap_slope",
           "inviscid_section_cl"]

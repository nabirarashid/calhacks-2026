"""Closed-form rear wing (PLAN.md B.5/B.10): a stand-in for W-B's rear_wing_v1. Zero network.

Textbook physics, deterministic, about 50 microseconds per call, same parameter and metric
names as the real solver, so the investigator and the panel can be built before it lands:
- lift-curve slope from lifting-line theory, a = a0 / (1 + a0 / (pi * e * AR_eff))
- endplates raise effective aspect ratio, AR_eff = AR * (1 + 1.9 h / b) (Hoerner)
- plain-flap effectiveness from thin-airfoil theory, tau = 1 - (theta_f - sin theta_f) / pi
- induced drag CL^2 / (pi * e * AR_eff); profile drag grows with CL^2, flap angle and endplate area
- a soft stall: past CL_max, lift saturates and profile drag rises sharply
It is NOT validated. The real solver (AeroSandbox + NeuralFoil) replaces it.
"""
import math
from typing import Dict, List, Mapping, Optional

from shared.contracts import CadSource, DesignSpace, Goal, MetricInfo, ParamSpec, ParamValue, canonicalize

SCORER_ID = "rear_wing_v1"
RHO, MU = 1.225, 1.81e-5
A0 = 2.0 * math.pi                 # thin-airfoil section slope, per rad
ALPHA_L0_DEG = -4.0                # inverted NACA 4412: lifts (downforce) at 0 deg
CL_MAX_CLEAN = 1.45
E_SPAN = 0.90

WING_SPACE = DesignSpace(
    id="rear_wing_v1",
    name="FSAE-style rear wing",
    scorer=SCORER_ID,
    parameters=[
        ParamSpec(name="aoa_deg", kind="continuous", unit="deg", min=0.0, max=16.0, step=0.5, default=6.0,
                  cad_ref="aoa_deg", description="Main element angle of attack"),
        ParamSpec(name="span_mm", kind="continuous", unit="mm", min=700.0, max=1000.0, step=5.0, default=850.0,
                  cad_ref="span_mm", description="Wing span (rule width limit)"),
        ParamSpec(name="chord_mm", kind="continuous", unit="mm", min=200.0, max=350.0, step=5.0, default=280.0,
                  cad_ref="chord_mm", description="Total chord, main element plus flap"),
        ParamSpec(name="flap_angle_deg", kind="continuous", unit="deg", min=0.0, max=35.0, step=0.5, default=15.0,
                  cad_ref="flap_angle_deg", description="Flap deflection"),
        ParamSpec(name="flap_chord_frac", kind="continuous", unit="", min=0.2, max=0.4, step=0.01, default=0.3,
                  cad_ref="flap_chord_frac", description="Flap chord as a fraction of total chord"),
        ParamSpec(name="endplate_height_mm", kind="continuous", unit="mm", min=100.0, max=300.0, step=5.0,
                  default=200.0, cad_ref="endplate_height_mm", description="Endplate height"),
    ],
    context={"velocity_mps": 25.0, "rho": RHO},
    source=CadSource(kind="onshape", mode="configuration", model_revision="r1"),
    notes=["Ranges from PLAN.md B.5; W-B owns the real solver and may narrow them before CP-B."],
)

CATALOG = [
    MetricInfo(name="downforce_n", unit="N", description="Downforce at design speed", better="higher",
               typical_min=20.0, typical_max=200.0),
    MetricInfo(name="drag_n", unit="N", description="Total wing drag at design speed", better="lower",
               typical_min=2.0, typical_max=40.0),
    MetricInfo(name="l_over_d", unit="", description="Downforce-to-drag ratio", better="higher",
               typical_min=2.0, typical_max=15.0),
    MetricInfo(name="drag_induced_n", unit="N", description="Induced (vortex) drag", better="lower",
               typical_min=0.5, typical_max=30.0),
    MetricInfo(name="drag_profile_n", unit="N", description="Profile (skin friction + pressure) drag",
               better="lower", typical_min=0.5, typical_max=15.0),
    MetricInfo(name="cl", unit="", description="Downforce coefficient", better="info",
               typical_min=0.0, typical_max=2.5),
    MetricInfo(name="stall_margin_deg", unit="deg", description="Angle of attack left before stall",
               better="higher", typical_min=-5.0, typical_max=15.0),
    MetricInfo(name="span_efficiency", unit="", description="Oswald span efficiency", better="info",
               typical_min=0.6, typical_max=1.0),
    MetricInfo(name="aspect_ratio_eff", unit="", description="Effective aspect ratio with endplates",
               better="info", typical_min=2.0, typical_max=10.0),
    MetricInfo(name="reynolds", unit="", description="Chord Reynolds number", better="info",
               typical_min=2.0e5, typical_max=8.0e5),
]  # type: List[MetricInfo]


def _flap_tau(cf: float) -> float:
    theta = math.acos(2.0 * cf - 1.0)
    return 1.0 - (theta - math.sin(theta)) / math.pi


def wing_metrics(params: Mapping[str, ParamValue], v: float = 25.0, rho: float = RHO) -> Dict[str, float]:
    aoa, b = float(params["aoa_deg"]), float(params["span_mm"]) / 1000.0
    c, df = float(params["chord_mm"]) / 1000.0, float(params["flap_angle_deg"])
    cf, h = float(params["flap_chord_frac"]), float(params["endplate_height_mm"]) / 1000.0
    s = b * c
    ar = b * b / s
    ar_eff = ar * (1.0 + 1.9 * h / b)
    e = E_SPAN - 0.08 * (df / 35.0)                              # flap loading pulls e down a little
    a = A0 / (1.0 + A0 / (math.pi * e * ar_eff))                 # 3D lift slope, per rad
    tau = _flap_tau(cf)
    alpha_eff = math.radians(aoa - ALPHA_L0_DEG) + 0.6 * tau * math.radians(df)   # 0.6 = viscous flap loss
    cl_lin = a * alpha_eff
    cl_max = CL_MAX_CLEAN + 0.9 * cf * math.sin(math.radians(min(df, 35.0))) * 2.0
    over = max(0.0, cl_lin - cl_max)
    cl = cl_lin - over * 0.85                                      # soft stall: lift saturates
    stall_margin = (cl_max - cl_lin) / (a * math.pi / 180.0)
    q = 0.5 * rho * v * v
    cdi = cl * cl / (math.pi * e * ar_eff)
    cdp = 0.010 + 0.006 * cl * cl + 0.00004 * df ** 1.5 + 0.004 * (2.0 * h * c) / s + 0.25 * over
    re = rho * v * c / MU
    out = {
        "downforce_n": q * s * cl, "drag_induced_n": q * s * cdi, "drag_profile_n": q * s * cdp,
        "cl": cl, "stall_margin_deg": stall_margin, "span_efficiency": e, "aspect_ratio_eff": ar_eff,
        "reynolds": re,
    }
    out["drag_n"] = out["drag_induced_n"] + out["drag_profile_n"]
    out["l_over_d"] = out["downforce_n"] / out["drag_n"]
    return {k: round(val, 4) for k, val in out.items()}


class FakeWingPlugin:
    """sim.plugins.ScorerPlugin shape, so sim.api.register_scorer("rear_wing_v1", PLUGIN) works."""

    def metric_catalog(self) -> List[MetricInfo]:
        return [m.model_copy() for m in CATALOG]

    def metrics(self, space: DesignSpace, params: Mapping[str, ParamValue],
                goal: Optional[Goal] = None) -> Dict[str, float]:
        ctx = dict(space.context, **(goal.context_overrides if goal else {}))
        return wing_metrics(canonicalize(space, dict(params)), float(ctx.get("velocity_mps", 25.0)),
                            float(ctx.get("rho", RHO)))

    def evaluate_metrics(self, space: DesignSpace, params: Mapping[str, ParamValue],
                         goal: Optional[Goal] = None, fidelity: str = "fast"):
        from sim.plugins import PluginEvaluation
        m = self.metrics(space, params, goal)
        warns = ["fake_wing: closed-form stand-in, not validated"]
        if m["stall_margin_deg"] < 0:
            warns.append("past stall: linear predictions do not hold")
        return PluginEvaluation(metrics=m, warnings=warns)

    def hifi(self, space: DesignSpace, params: Mapping[str, ParamValue], goal: Optional[Goal] = None):
        return self.evaluate_metrics(space, params, goal, fidelity="high")


PLUGIN = FakeWingPlugin()

__all__ = ["SCORER_ID", "WING_SPACE", "CATALOG", "wing_metrics", "FakeWingPlugin", "PLUGIN"]

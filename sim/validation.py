"""Regenerate the validation table in sim/PHYSICS.md (W-B, PLAN.md v4 B5).

    python -m sim.validation            # markdown table to stdout

Every row is computed from the code at run time, against an independent reference
(closed-form theory or published section data), so the table cannot drift from the
model. Deterministic, no network, ~10 s.
"""
import math
import warnings
from typing import List, Tuple

warnings.filterwarnings("ignore")

Row = Tuple[str, str, str, str]          # quantity, reference, result, verdict


def _asb():
    import aerosandbox as asb
    return asb


def _rect_wing(airfoil, span=0.85, chord=0.28):
    asb = _asb()
    wing = asb.Wing(name="w", symmetric=True, xsecs=[
        asb.WingXSec(xyz_le=[0, 0, 0], chord=chord, airfoil=airfoil),
        asb.WingXSec(xyz_le=[0, span / 2, 0], chord=chord, airfoil=airfoil)])
    return asb.Airplane(wings=[wing], s_ref=span * chord, c_ref=chord, b_ref=span)


def _vlm(airplane, alpha, res=(12, 6), v=25.0):
    asb = _asb()
    return asb.VortexLatticeMethod(
        airplane=airplane, op_point=asb.OperatingPoint(velocity=v, alpha=alpha),
        spanwise_resolution=res[0], chordwise_resolution=res[1]).run()


def _helmbold(ar):
    return 2 * math.pi * ar / (2 + math.sqrt(ar ** 2 + 4))


def wing_rows() -> List[Row]:
    import numpy as np
    from sim.plugins import rear_wing_v1 as rw
    asb = _asb()
    rows = []
    span, chord = 0.85, 0.28
    ar = span / chord
    slope = _helmbold(ar)

    # 1-2. VLM lift vs Helmbold, cambered and symmetric
    for name, foil, a_l0 in (("NACA 4412", "naca4412", rw.ALPHA_L0_NACA4412_DEG),
                             ("NACA 0012", "naca0012", 0.0)):
        ap = _rect_wing(asb.Airfoil(foil))
        errs = []
        for a in (2.0, 4.0, 6.0):
            theory = slope * math.radians(a - a_l0)
            errs.append(100 * (float(_vlm(ap, a)["CL"]) - theory) / theory)
        rows.append(("Lift slope, %s, AR %.2f, AoA 2-6 deg" % (name, ar),
                     "Helmbold low-AR lifting line",
                     "%+.1f to %+.1f %%" % (min(errs), max(errs)),
                     "pass" if max(abs(e) for e in errs) < 5 else "FAIL"))

    # 3. Flap increment vs Glauert thin-airfoil flap theory
    e_frac = 0.30
    errs = []
    for d in (5.0, 10.0, 15.0, 20.0):
        foil = asb.Airfoil("naca4412").add_control_surface(deflection=d, hinge_point_x=1 - e_frac)
        cl = float(_vlm(_rect_wing(foil), 0.0)["CL"])
        expect = slope * (math.radians(-rw.ALPHA_L0_NACA4412_DEG)
                          + rw.glauert_flap_slope(e_frac) * math.radians(d) / (2 * math.pi))
        errs.append(100 * (cl - expect) / expect)
    rows.append(("Flap lift increment, 5-20 deg", "Glauert thin-airfoil flap theory",
                 "%+.1f to %+.1f %%" % (min(errs), max(errs)),
                 "pass" if max(abs(e) for e in errs) < 5 else "FAIL"))

    # 4. VLM mesh convergence on the default design
    base = {"aoa_deg": 6.0, "span_mm": 850.0, "chord_mm": 280.0, "flap_angle_deg": 15.0,
            "flap_chord_frac": 0.30, "endplate_height_mm": 200.0}
    fast = rw.solve(base)[0]["cl"]
    conv = rw.solve(base, high_fidelity=True)[0]["cl"]
    rows.append(("VLM resolution, default design", "converged %dx%d lattice" % rw.VLM_HIFI,
                 "%+.2f %% at %dx%d" % (100 * (fast - conv) / conv, rw.VLM_FAST[0], rw.VLM_FAST[1]),
                 "pass" if abs(fast - conv) / conv < 0.03 else "FAIL"))

    # 5. Span efficiency vs Anderson's rectangular-wing curve
    d6 = 1 / rw.glauert_span_efficiency(6.0) - 1
    rows.append(("Span efficiency, rectangular wing", "Anderson ch. 5: delta about 0.05 at AR 6",
                 "delta %.3f at AR 6; e %.3f here" % (d6, rw.glauert_span_efficiency(ar)),
                 "pass" if 0.04 < d6 < 0.06 else "FAIL"))

    # 6. Induced drag, lifting line vs VLM near field
    res = _vlm(rw._vlm_airplane(span, chord, 15.0, 0.30), 6.0)
    cl = float(res["CL"])
    ll = cl ** 2 / (math.pi * rw.glauert_span_efficiency(ar) * ar)
    rows.append(("Induced drag, default flapped wing", "independent VLM near-field estimate",
                 "%+.1f %%" % (100 * (ll - float(res["CD"])) / float(res["CD"])),
                 "pass" if abs(ll - float(res["CD"])) / float(res["CD"]) < 0.10 else "FAIL"))

    # 7. NeuralFoil section data vs Abbott & von Doenhoff
    foil = asb.Airfoil("naca4412")
    alphas = np.linspace(-6.0, 22.0, 57)
    cls = np.asarray(foil.get_aero_from_neuralfoil(alpha=alphas, Re=1.0e6)["CL"]).ravel()
    a_l0 = float(np.interp(0.0, cls[:20], alphas[:20]))
    lin = (alphas >= -2.0) & (alphas <= 6.0)
    sl = float(np.polyfit(alphas[lin], cls[lin], 1)[0])
    ok = -5 < a_l0 < -3 and 0.09 < sl < 0.12 and 1.3 < cls.max() < 1.8
    rows.append(("NACA 4412 section, Re 1e6 (NeuralFoil)",
                 "Abbott & von Doenhoff: aL0 ~ -4 deg, ~0.1/deg, CLmax 1.3-1.8",
                 "aL0 %.1f deg, %.3f/deg, CLmax %.2f at %.1f deg"
                 % (a_l0, sl, cls.max(), alphas[int(np.argmax(cls))]),
                 "pass" if ok else "FAIL"))

    # 8. Viscous fixed point
    rw_iters = rw.VISCOUS_ITERATIONS
    try:
        rw.VISCOUS_ITERATIONS = 4
        four = rw.solve(base)[0]["downforce_n"]
        rw.VISCOUS_ITERATIONS = 10
        ten = rw.solve(base)[0]["downforce_n"]
    finally:
        rw.VISCOUS_ITERATIONS = rw_iters
    rows.append(("Viscous-correction fixed point", "10 iterations",
                 "%.3f %% at 4" % (100 * abs(four - ten) / ten),
                 "pass" if abs(four - ten) / ten < 1e-3 else "FAIL"))

    # 9. Dynamic-pressure scaling
    slow = rw.solve(base, velocity=25.0)[0]["downforce_n"]
    quick = rw.solve(base, velocity=50.0)[0]["downforce_n"]
    rows.append(("Downforce at 2x speed", "q = 0.5 rho V^2: x4, less a Reynolds effect",
                 "x%.2f" % (quick / slow), "pass" if 3.6 < quick / slow < 4.4 else "FAIL"))
    return rows


def rejected_rows() -> List[Row]:
    """Why the plan's AeroBuildup fast path lost the lift job. Kept as evidence."""
    asb = _asb()
    span, chord = 0.85, 0.28
    slope = _helmbold(span / chord)
    ap = _rect_wing(asb.Airfoil("naca4412"))
    ratios = []
    for a in (0.0, 4.0, 8.0):
        theory = slope * math.radians(a + 4.0)
        ab = float(asb.AeroBuildup(ap, asb.OperatingPoint(velocity=25.0, alpha=a)).run()["CL"])
        ratios.append(ab / theory)
    rows = [("AeroBuildup lift, NACA 4412, AoA 0-8 deg", "Helmbold low-AR lifting line",
             "x%.2f to x%.2f (worst at AoA 0)" % (min(ratios), max(ratios)), "rejected")]

    from sim.plugins import rear_wing_v1 as rw
    cs = []
    for d in (0.0, 15.0, 30.0):
        flap = [asb.ControlSurface(name="f", symmetric=True, hinge_point=0.7, deflection=d)]
        foil = asb.Airfoil("naca4412")
        w = asb.Wing(name="w", symmetric=True, xsecs=[
            asb.WingXSec(xyz_le=[0, 0, 0], chord=chord, airfoil=foil, control_surfaces=flap),
            asb.WingXSec(xyz_le=[0, span / 2, 0], chord=chord, airfoil=foil, control_surfaces=flap)])
        cs.append(float(_vlm(asb.Airplane(wings=[w], s_ref=span * chord, c_ref=chord,
                                           b_ref=span), 6.0)["CL"]))
    rows.append(("VLM with ControlSurface flaps, 0/15/30 deg", "should rise with flap",
                 "CL %.4f / %.4f / %.4f (flap ignored)" % tuple(cs), "rejected"))
    del rw
    return rows


def fin_rows() -> List[Row]:
    import json
    import os
    from shared import fin_geometry
    from shared.contracts import Goal
    from shared.manifest import ProjectManifest
    from sim import aero, api
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "projects", "fin_reference", "r1.json")) as fh:
        space = ProjectManifest(**json.load(fh)).design_space
    goal = Goal(source_text="", objectives=[], constraints=[])
    base = {p.name: p.default for p in space.parameters}
    asb = aero._load_aerosandbox()
    body_area = math.pi * (float(space.context["body_diameter_mm"]) / 2000.0) ** 2
    ratios = []
    for over in ({}, {"sweep_deg": 0.0}, {"sweep_deg": 60.0}, {"semi_span": 90.0},
                 {"semi_span": 30.0}, {"taper_ratio": 1.0}, {"taper_ratio": 0.2}):
        p = dict(base, **over)
        bar = api.evaluate(space, p, goal).metrics["cn_alpha_fins"]
        _, cna, _, _, _ = aero._run_aerosandbox(asb, p, 120.0, 0.0, 2.0, False)
        area = fin_geometry.derived(p)["area_mm2"] / 1e6
        ratios.append(cna * int(p["fin_count"]) * area / body_area / bar)
    rows = [("Fin lift slope, 7 designs across the box", "Barrowman (1966) vs AeroSandbox",
             "ratio %.2f to %.2f (default %.2f)" % (min(ratios), max(ratios), ratios[0]),
             "pass" if all(0.6 <= r <= 1.6 for r in ratios) else "FAIL")]

    flutter = [api.evaluate(space, dict(base, thickness=t), goal).metrics["flutter_margin"]
               for t in (2.0, 5.0)]
    exponent = math.log(flutter[1] / flutter[0]) / math.log(5.0 / 2.0)
    rows.append(("Flutter vs thickness, 2-5 mm", "NACA TN 4197: V_f ~ (t/c)^1.5",
                 "exponent %.2f" % exponent, "pass" if abs(exponent - 1.5) < 0.1 else "FAIL"))
    return rows


def markdown() -> str:
    def table(title, rows):
        out = ["**%s**" % title, "",
               "| Quantity | Reference | Result | |", "|---|---|---|---|"]
        out += ["| %s | %s | %s | %s |" % r for r in rows]
        return "\n".join(out) + "\n"
    return "\n".join([
        table("Rear wing (`rear_wing_v1`)", wing_rows()),
        table("Measured and rejected (why the lift path is VLM, not AeroBuildup)", rejected_rows()),
        table("Rocket fin (`fin_v1`)", fin_rows()),
    ])


if __name__ == "__main__":
    print(markdown())

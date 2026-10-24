"""Golden tests for rear_wing_v1 (W-B, PLAN.md v4 B3). Zero network.

Four groups:
  1. the frozen B.5 contract (names other workstreams build against),
  2. each physics source against an independent reference,
  3. the trends the hypothesis loop relies on,
  4. engineering properties: determinism, speed, convergence.

References are closed-form theory (Helmbold, Glauert, Prandtl) or published
section data (Abbott & von Doenhoff, *Theory of Wing Sections*). Where a test
uses a band rather than a point value, it is because the reference itself is a
band at this Reynolds number, not to loosen the check.
"""
import math
import time
import warnings

import pytest

pytest.importorskip("aerosandbox", reason="AeroSandbox is not installed")
pytest.importorskip("neuralfoil", reason="NeuralFoil is not installed")

from shared.contracts import CadSource, DesignSpace, Goal, ParamSpec   # noqa: E402
from sim import api                                                     # noqa: E402
from sim.plugins import rear_wing_v1 as rw                              # noqa: E402

warnings.filterwarnings("ignore")

# PLAN.md v4 B.5, frozen Sat 15:01. These are the names every workstream uses.
FROZEN_PARAMS = [
    ("aoa_deg", "deg", 0.0, 16.0, 6.0),
    ("span_mm", "mm", 700.0, 1000.0, 850.0),
    ("chord_mm", "mm", 200.0, 350.0, 280.0),
    ("flap_angle_deg", "deg", 0.0, 35.0, 15.0),
    ("flap_chord_frac", "", 0.20, 0.40, 0.30),
    ("endplate_height_mm", "mm", 100.0, 300.0, 200.0),
]
FROZEN_METRICS = ["downforce_n", "drag_n", "l_over_d", "drag_induced_n", "drag_profile_n",
                  "cl", "stall_margin_deg", "span_efficiency", "aspect_ratio_eff", "reynolds"]

SPACE = DesignSpace(
    id="rear_wing", name="Rear wing", scorer="rear_wing_v1",
    parameters=[ParamSpec(name=n, kind="continuous", unit=u, min=lo, max=hi, default=d,
                          cad_ref=n) for n, u, lo, hi, d in FROZEN_PARAMS],
    context={"velocity_mps": 25.0, "rho": 1.225}, source=CadSource(kind="mock"))
DEFAULTS = {n: d for n, _, _, _, d in FROZEN_PARAMS}
PLUGIN = rw.PLUGIN


def _m(**over):
    return PLUGIN.evaluate_metrics(SPACE, dict(DEFAULTS, **over)).metrics


def _ev(**over):
    return PLUGIN.evaluate_metrics(SPACE, dict(DEFAULTS, **over))


# ------------------------------------------------------------ 1. frozen contract

def test_metric_names_match_the_frozen_b5_contract():
    assert [m.name for m in PLUGIN.metric_catalog()] == FROZEN_METRICS


def test_every_metric_is_produced_and_finite():
    out = _m()
    assert list(out) == FROZEN_METRICS
    assert all(math.isfinite(v) for v in out.values())


def test_registered_as_a_spawn_safe_builtin_scorer():
    assert api.spawn_resolvable("rear_wing_v1") is True
    assert [m.name for m in api.metric_catalog("rear_wing_v1")] == FROZEN_METRICS


def test_refuses_a_space_for_another_scorer():
    with pytest.raises(ValueError):
        PLUGIN.evaluate_metrics(SPACE.model_copy(update={"scorer": "fin_v1"}), DEFAULTS)


def test_objective_ranges_cover_the_design_space():
    """Calibrated against a 300-sample LHS (p2..p98). The default must sit inside
    its range, or aggregation would score it flat."""
    cat = {m.name: m for m in PLUGIN.metric_catalog()}
    out = _m()
    for name in ("downforce_n", "drag_n", "l_over_d", "stall_margin_deg"):
        assert cat[name].typical_min < out[name] < cat[name].typical_max, name


# ------------------------------------------------- 2. physics vs independent refs

def test_vlm_lift_matches_helmbold_low_aspect_ratio_theory():
    """VLM was chosen for lift because it matches theory on the cambered section.
    Helmbold: a = 2 pi AR / (2 + sqrt(AR^2 + 4)); NACA 4412 alpha_L0 = -4 deg."""
    span, chord = 0.85, 0.28
    ar = span / chord
    slope = 2.0 * math.pi * ar / (2.0 + math.sqrt(ar ** 2 + 4.0))
    for alpha in (2.0, 4.0, 6.0):
        theory = slope * math.radians(alpha - rw.ALPHA_L0_NACA4412_DEG)
        vlm = rw._vlm_cl(span, chord, 0.0, 0.30, alpha, 25.0, rw.VLM_FAST)
        assert abs(vlm - theory) / theory < 0.05, (alpha, vlm, theory)


def test_glauert_span_efficiency_follows_the_rectangular_wing_curve():
    """Anderson, Fundamentals of Aerodynamics, ch. 5: for a rectangular wing the
    induced-drag factor delta rises with AR, ~0.05 by AR 6."""
    deltas = [1.0 / rw.glauert_span_efficiency(ar) - 1.0 for ar in (2, 3, 4, 6, 8, 10)]
    assert all(a < b for a, b in zip(deltas, deltas[1:])), deltas
    assert 0.04 < deltas[3] < 0.06
    assert all(0.9 < rw.glauert_span_efficiency(ar) <= 1.0 for ar in (2, 3, 6, 10))


def test_glauert_solution_is_converged_in_stations():
    a = rw.glauert_span_efficiency(3.036, stations=12)
    b = rw.glauert_span_efficiency(3.036, stations=48)
    assert abs(a - b) < 1e-4


def test_glauert_flap_slope_limits():
    """No flap gives no increment; a full-chord flap is just angle of attack (2 pi)."""
    assert rw.glauert_flap_slope(1e-9) == pytest.approx(0.0, abs=1e-3)
    assert rw.glauert_flap_slope(1.0) == pytest.approx(2.0 * math.pi, rel=1e-9)
    assert rw.glauert_flap_slope(0.30) == pytest.approx(4.152, abs=1e-3)


def test_induced_drag_agrees_with_an_independent_vlm_estimate_within_10_percent():
    """B3: lifting-line induced drag CL^2 / (pi e AR) vs VLM's own near-field value,
    on the same inviscid geometric wing (no endplates, no viscous correction)."""
    import aerosandbox as asb
    span, chord, aoa = 0.85, 0.28, 6.0
    ar = span / chord
    res = asb.VortexLatticeMethod(
        airplane=rw._vlm_airplane(span, chord, 15.0, 0.30),
        op_point=asb.OperatingPoint(velocity=25.0, alpha=aoa),
        spanwise_resolution=rw.VLM_FAST[0], chordwise_resolution=rw.VLM_FAST[1]).run()
    cl = float(res["CL"])
    lifting_line = cl ** 2 / (math.pi * rw.glauert_span_efficiency(ar) * ar)
    vlm = float(res["CD"])
    assert abs(lifting_line - vlm) / vlm < 0.10, (lifting_line, vlm)


def test_neuralfoil_naca4412_section_against_abbott_and_von_doenhoff():
    """Bands from Theory of Wing Sections for NACA 4412: zero-lift angle about
    -4 deg, linear lift slope about 0.1 per deg, CLmax 1.3-1.8, stall 11-17 deg."""
    import numpy as np
    import aerosandbox as asb
    foil = asb.Airfoil("naca4412")
    alphas = np.linspace(-6.0, 22.0, 57)
    cl = np.asarray(foil.get_aero_from_neuralfoil(alpha=alphas, Re=1.0e6)["CL"]).ravel()
    alpha_l0 = float(np.interp(0.0, cl[:20], alphas[:20]))
    lin = (alphas >= -2.0) & (alphas <= 6.0)
    slope = float(np.polyfit(alphas[lin], cl[lin], 1)[0])
    assert -5.0 < alpha_l0 < -3.0, alpha_l0
    assert 0.09 < slope < 0.12, slope
    assert 1.3 < float(cl.max()) < 1.8
    assert 11.0 < float(alphas[int(np.argmax(cl))]) < 17.0


def test_hoerner_endplate_aspect_ratio():
    assert rw.hoerner_ar_eff(3.0, 0.0, 1.0) == pytest.approx(3.0)
    assert rw.hoerner_ar_eff(3.0, 0.2, 0.85) == pytest.approx(3.0 * (1 + 1.9 * 0.2 / 0.85))
    with pytest.raises(ValueError):
        rw.hoerner_ar_eff(3.0, 0.2, 0.0)


def test_skin_friction_is_the_turbulent_flat_plate_value():
    assert rw.flat_plate_cf_turbulent(1.0e6) == pytest.approx(0.074 * 1.0e6 ** -0.2)


# --------------------------------------------------------- 3. trends the loop uses

def test_aoa_raises_downforce_until_stall_then_it_falls():
    attached = [_m(aoa_deg=a)["downforce_n"] for a in (0.0, 3.0, 6.0, 9.0)]
    assert all(x < y for x, y in zip(attached, attached[1:])), attached
    assert _m(aoa_deg=16.0)["downforce_n"] < max(attached)
    assert _m(aoa_deg=16.0)["stall_margin_deg"] < 0.0 < _m(aoa_deg=6.0)["stall_margin_deg"]


def test_flap_raises_downforce_and_then_turns_over():
    """The plain-flap ceiling: a strong lever at small angles, diminishing
    returns, then an interior peak once the flap's boundary layer separates.

    Plain (unslotted) flaps typically lose effectiveness beyond ~15-25 deg, so the
    peak is asserted to be interior rather than pinned to a value: where it
    falls depends on loading, and a test that hard-coded it would only encode
    the model's current output.
    """
    angles = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0]
    dfs = [_m(flap_angle_deg=f)["downforce_n"] for f in angles]
    assert dfs[0] < dfs[1] < dfs[2] < dfs[3], dfs[:4]
    assert (dfs[2] - dfs[0]) > 3.0 * (dfs[4] - dfs[2]), "flap gains must diminish"
    peak = max(range(len(dfs)), key=lambda i: dfs[i])
    assert 0 < peak < len(dfs) - 1, "peak must be interior, got flap %g" % angles[peak]
    assert dfs[-1] < dfs[peak], "downforce must fall past the peak"


def test_flap_always_costs_drag():
    drags = [_m(flap_angle_deg=f)["drag_n"] for f in (0.0, 10.0, 20.0, 30.0, 35.0)]
    assert all(x < y for x, y in zip(drags, drags[1:])), drags


def test_viscous_correction_only_removes_lift_and_grows_with_flap():
    ks = [_ev(flap_angle_deg=f).diagnostics["viscous_factor"] for f in (0.0, 15.0, 25.0, 35.0)]
    assert all(k <= 1.0 for k in ks)
    assert all(x >= y for x, y in zip(ks, ks[1:])), ks
    assert ks[-1] < 0.7


def test_span_cuts_induced_drag_per_unit_downforce():
    """With chord fixed, more span adds area and AR together, and at fixed CL the
    two cancel in raw induced drag (CL^2 q c^2 / pi e). The physically meaningful
    claim is induced drag per newton of downforce, so that is what is asserted."""
    ratios = []
    for b in (700.0, 850.0, 1000.0):
        out = _m(span_mm=b)
        ratios.append(out["drag_induced_n"] / out["downforce_n"])
    assert all(x > y for x, y in zip(ratios, ratios[1:])), ratios


def test_endplates_add_downforce_and_cut_induced_drag():
    low, high = _m(endplate_height_mm=100.0), _m(endplate_height_mm=300.0)
    assert high["downforce_n"] > low["downforce_n"]
    assert high["drag_induced_n"] < low["drag_induced_n"]
    assert high["aspect_ratio_eff"] > low["aspect_ratio_eff"]


def test_flap_lowers_the_section_stall_angle():
    stalls = [_ev(flap_angle_deg=f).diagnostics["stall_angle_deg"] for f in (0.0, 15.0, 35.0)]
    assert stalls[0] > stalls[1] > stalls[2], stalls


def test_downforce_scales_with_dynamic_pressure():
    """q scaling: doubling speed quadruples downforce, less a small Reynolds effect."""
    slow = PLUGIN.evaluate_metrics(SPACE, DEFAULTS).metrics["downforce_n"]
    goal = Goal(source_text="", objectives=[], constraints=[],
                context_overrides={"velocity_mps": 50.0})
    fast = PLUGIN.evaluate_metrics(SPACE, DEFAULTS, goal).metrics["downforce_n"]
    assert 3.6 < fast / slow < 4.4, fast / slow


# ------------------------------------------------------ 4. engineering properties

def test_viscous_fixed_point_is_converged():
    original = rw.VISCOUS_ITERATIONS
    try:
        rw.VISCOUS_ITERATIONS = 4
        four = rw.solve(DEFAULTS)[0]["downforce_n"]
        rw.VISCOUS_ITERATIONS = 10
        ten = rw.solve(DEFAULTS)[0]["downforce_n"]
    finally:
        rw.VISCOUS_ITERATIONS = original
    assert abs(four - ten) / ten < 1e-3


def test_hifi_is_a_mesh_refinement_check_within_3_percent():
    hi = PLUGIN.hifi(SPACE, DEFAULTS)
    assert abs(hi.diagnostics["refinement_change_pct"]) < 3.0
    assert hi.diagnostics["vlm_span_panels"] > rw.VLM_FAST[0]
    assert not [w for w in hi.warnings if "refinement" in w]


def test_deterministic():
    assert _m() == _m()


def test_fast_evaluation_is_under_the_100_ms_budget():
    _m()                                              # warm imports and caches
    times = []
    for _ in range(5):
        t = time.perf_counter()
        _m(aoa_deg=7.0)
        times.append((time.perf_counter() - t) * 1000.0)
    assert sorted(times)[2] < 100.0, times


def test_stalled_design_is_flagged_not_hidden():
    ev = _ev(aoa_deg=16.0)
    assert ev.metrics["stall_margin_deg"] < 0.0
    assert any("stalled" in w for w in ev.warnings)


# ------------------------------------------------ 5. against W-C's real manifest

def test_accepts_the_committed_rear_wing_project_manifest():
    """The solver must score W-C's projects/rear_wing/r1.json, not just the
    test-local space above: same scorer id, context keys and frozen names."""
    import json
    import os
    from shared.manifest import ProjectManifest

    path = os.path.join(os.path.dirname(__file__), "..", "..", "projects", "rear_wing", "r1.json")
    if not os.path.exists(path):
        pytest.skip("projects/rear_wing/r1.json not committed yet")
    with open(path) as fh:
        manifest = ProjectManifest(**json.load(fh))
    space = manifest.design_space
    assert space.scorer == "rear_wing_v1"
    assert [p.name for p in space.parameters] == [n for n, _, _, _, _ in FROZEN_PARAMS]
    for spec, (name, unit, lo, hi, default) in zip(space.parameters, FROZEN_PARAMS):
        assert (spec.min, spec.max, spec.default) == (lo, hi, default), name
    out = PLUGIN.evaluate_metrics(space, {p.name: p.default for p in space.parameters}).metrics
    assert list(out) == FROZEN_METRICS
    assert out == _m(), "the committed manifest and the frozen B.5 space must agree"


def test_metric_names_match_fake_wing_so_the_swap_is_seamless():
    """backend.wiring falls back to fake_wing until this scorer is registered;
    identical names mean the investigator never notices the swap."""
    from shared.mocks import fake_wing
    fake = getattr(fake_wing, "CATALOG", None) or fake_wing.metric_catalog()
    assert [m.name for m in fake] == FROZEN_METRICS

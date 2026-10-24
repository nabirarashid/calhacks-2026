"""Independent unit and monotonicity checks for the ``fin_v1`` physics."""

import json
import math
from pathlib import Path

import pytest

from shared.contracts import DesignSpace, Goal, canonicalize
from sim.aero import (
    aero_metrics,
    aerosandbox_available,
    rectangular_reference_lift_slope,
)
from sim.api import evaluate
from sim.barrowman import (
    fin_center_of_pressure_mm,
    fin_normal_force_slope,
    stability,
)
from sim.mass import mass_properties


FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"
SPACE = DesignSpace.model_validate_json(
    (FIXTURES / "design_space_fin.json").read_text(encoding="utf-8")
)
GOAL = Goal.model_validate_json(
    (FIXTURES / "goal_example.json").read_text(encoding="utf-8")
)


def _params(**updates):
    return canonicalize(SPACE, updates)


def test_square_rectangle_mass_has_correct_mm_to_cm_conversion() -> None:
    """90 x 60 x 3 mm = 16.2 cm^3, or 20.088 g at 1.24 g/cm^3."""
    params = _params(
        root_chord=90.0,
        taper_ratio=1.0,
        semi_span=60.0,
        sweep_deg=0.0,
        thickness=3.0,
        edge_profile="square",
        fin_count=4,
    )
    result = mass_properties(params, SPACE.context)
    assert result.volume_mm3 == pytest.approx(16200.0)
    assert result.fin_mass_g == pytest.approx(20.1, abs=0.1)
    assert result.fin_mass_total_g == pytest.approx(80.352)


def test_installed_aerosandbox_executes_real_fast_and_hifi_paths() -> None:
    """An importable solver must not silently degrade because of bad geometry."""
    if not aerosandbox_available():
        pytest.skip("AeroSandbox is not installed; analytic fallback is tested elsewhere")
    params = _params()
    fast = aero_metrics(params, SPACE.context)
    high = aero_metrics(params, SPACE.context, high_fidelity=True)
    assert fast.method == "aerosandbox_aerobuildup"
    assert high.method == "aerosandbox_vlm"
    assert fast.warnings == ()
    assert high.warnings == ()
    assert fast.drag_n > 0.0 and high.drag_n > 0.0
    assert high.linearity_error_pct < 10.0


def test_rectangular_aerobuildup_slope_matches_finite_wing_theory() -> None:
    if not aerosandbox_available():
        pytest.skip("AeroSandbox is not installed")
    params = _params(
        root_chord=90.0,
        taper_ratio=1.0,
        semi_span=60.0,
        sweep_deg=0.0,
        thickness=3.0,
        edge_profile="beveled",
    )
    # Frozen pair convention: AR = (2s)^2 / (2A) = 2s^2/A.
    area_mm2 = 60.0 * 90.0
    aspect_ratio = 2.0 * 60.0 ** 2 / area_mm2
    theory = 2.0 * math.pi * aspect_ratio / (aspect_ratio + 2.0)
    actual = rectangular_reference_lift_slope(params, SPACE.context)
    assert actual == pytest.approx(theory, rel=0.15)


def test_increasing_span_increases_stability_mass_and_drag() -> None:
    low = evaluate(SPACE, _params(semi_span=40.0), GOAL)
    high = evaluate(SPACE, _params(semi_span=80.0), GOAL)

    assert high.metrics["stability_margin_cal"] > low.metrics["stability_margin_cal"]
    assert high.metrics["fin_mass_total_g"] > low.metrics["fin_mass_total_g"]
    # Assert only direction, not a solver-specific value: both AeroSandbox and
    # the explicit analytic fallback should reflect the doubled fin area.
    assert high.metrics["drag_n"] > low.metrics["drag_n"] > 0.0


def test_increasing_thickness_increases_mass_and_flutter_velocity() -> None:
    thin = evaluate(SPACE, _params(thickness=2.0), GOAL)
    thick = evaluate(SPACE, _params(thickness=5.0), GOAL)

    assert thick.metrics["fin_mass_total_g"] > thin.metrics["fin_mass_total_g"]
    assert thick.metrics["flutter_velocity_mps"] > thin.metrics["flutter_velocity_mps"]


def test_increasing_sweep_moves_fin_and_combined_cp_aft_at_fixed_area() -> None:
    unswept = _params(sweep_deg=0.0)
    swept = _params(sweep_deg=50.0)
    body_length_mm = float(SPACE.context["body_length_mm"])

    assert fin_center_of_pressure_mm(swept, body_length_mm) > fin_center_of_pressure_mm(
        unswept, body_length_mm
    )
    assert stability(swept, SPACE.context).cp_mm > stability(
        unswept, SPACE.context
    ).cp_mm


def test_lower_taper_ratio_reduces_tip_chord_and_mass() -> None:
    lower_tip_chord = _params(taper_ratio=0.2)
    higher_tip_chord = _params(taper_ratio=0.9)
    low = mass_properties(lower_tip_chord, SPACE.context)
    high = mass_properties(higher_tip_chord, SPACE.context)

    assert low.fin_mass_g < high.fin_mass_g
    assert low.fin_mass_total_g < high.fin_mass_total_g


def test_barrowman_rectangular_fin_reference_values() -> None:
    """Check an unswept rectangle against independently calculated values.

    Reference geometry: c_r=c_t=100 mm, s=50 mm, D=100 mm, four fins,
    1,000 mm body, and 200 mm tangent-ogive nose. For this shape the mid-chord
    line is 50 mm, K_fb=1.5, fin CP is 925 mm, and the hand-calculated values
    below follow directly from the frozen Barrowman equations.
    """
    params = {
        "root_chord": 100.0,
        "taper_ratio": 1.0,
        "semi_span": 50.0,
        "sweep_deg": 0.0,
        "thickness": 3.0,
        "edge_profile": "square",
        "fin_count": 4,
    }
    context = {
        "body_diameter_mm": 100.0,
        "body_length_mm": 1000.0,
        "nose_length_mm": 200.0,
        "mass_without_fins_g": 1000.0,
        "cg_without_fins_mm": 500.0,
        "density_g_cm3": 1.24,
    }

    # Independent hand calculation, retained as constants so changes to the
    # production implementation cannot silently redefine the reference.
    expected_cn_alpha = 2.8328157299974763
    expected_fin_cp_mm = 925.0
    expected_cp_mm = 580.770032845662
    expected_cg_mm = 531.1615785554728
    expected_margin_cal = 0.49608454290189113

    assert fin_normal_force_slope(params, 100.0) == pytest.approx(
        expected_cn_alpha, rel=1e-12
    )
    assert fin_center_of_pressure_mm(params, 1000.0) == pytest.approx(
        expected_fin_cp_mm, rel=1e-12
    )
    result = stability(params, context)
    assert result.cn_alpha_fins == pytest.approx(expected_cn_alpha, rel=1e-12)
    assert result.fin_cp_mm == pytest.approx(expected_fin_cp_mm, rel=1e-12)
    assert result.nose_cp_mm == pytest.approx(93.2, rel=1e-12)
    assert result.cp_mm == pytest.approx(expected_cp_mm, rel=1e-12)
    assert result.cg_mm == pytest.approx(expected_cg_mm, rel=1e-12)
    assert result.stability_margin_cal == pytest.approx(
        expected_margin_cal, rel=1e-12
    )


def test_physics_outputs_are_finite_at_all_continuous_corners() -> None:
    """Guard against singular formulas at the frozen parameter bounds."""
    continuous = [p for p in SPACE.parameters if p.kind == "continuous"]
    for mask in range(1 << len(continuous)):
        values = {}
        for index, parameter in enumerate(continuous):
            values[parameter.name] = parameter.max if mask & (1 << index) else parameter.min
        score = evaluate(SPACE, canonicalize(SPACE, values), GOAL)
        assert all(math.isfinite(value) for value in score.metrics.values())
        assert math.isfinite(score.aggregate)

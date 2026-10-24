"""Golden tests for structural_analytic_v1 (W-B, P3-B3). Zero network.

Three kinds of check:
  1. closed-form mechanics against independent hand calculations,
  2. fail-closed behaviour when an engineering input is missing,
  3. sensitivity directions, which is what an optimizer actually relies on.
"""
import json
import os

import pytest

from shared.contracts import Goal
from shared.manifest import ProjectManifest
from sim.adapters import structural_analytic_v1 as sa

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "fixtures", "v2")


def _manifest():
    with open(os.path.join(FIXTURES, "manifest_bracket.json")) as fh:
        return ProjectManifest(**json.load(fh))


def _goal():
    with open(os.path.join(FIXTURES, "goal_bracket.json")) as fh:
        return Goal(**json.load(fh))


def _defaults(m):
    return {p.name: p.default for p in m.design_space.parameters}


# ------------------------------------------------------------------ mechanics

def test_section_properties_plate_only_matches_closed_form():
    """A plate with no rib must reduce to b h^3 / 12 and c = h/2 exactly."""
    inertia, c = sa.section_properties(30.0, 5.0, 0.0, 3.0)
    assert inertia == pytest.approx(30.0 * 5.0 ** 3 / 12.0, rel=1e-12)
    assert c == pytest.approx(2.5, rel=1e-12)


def test_rib_stiffens_and_moves_the_neutral_axis():
    plain, c_plain = sa.section_properties(30.0, 5.0, 0.0, 3.0)
    ribbed, c_ribbed = sa.section_properties(30.0, 5.0, 8.0, 3.0)
    assert ribbed > 4.0 * plain, "a rib should several-fold the second moment"
    assert c_ribbed > c_plain


def test_hole_kt_tends_to_three_for_a_small_hole_in_a_wide_plate():
    """Heywood's factor must recover the classical Kt = 3 limit."""
    assert sa.hole_kt(0.01, 100.0) == pytest.approx(3.0, abs=0.01)
    assert sa.hole_kt(0.1, 100.0) == pytest.approx(3.0, abs=0.02)


def test_hole_kt_falls_as_the_hole_fills_the_width():
    wide = sa.hole_kt(2.0, 30.0)
    narrow = sa.hole_kt(15.0, 30.0)
    assert 2.0 < narrow < wide < 3.0


def test_fillet_kt_is_monotone_decreasing_in_r_over_t():
    vals = [sa.fillet_kt(r, 5.0)[0] for r in (0.5, 1.0, 1.5, 2.5, 5.0, 10.0)]
    assert all(a > b for a, b in zip(vals, vals[1:])), vals
    assert vals[0] > 1.6 and vals[-1] < 1.3


def test_fillet_kt_flags_r_over_t_below_the_chart():
    kt, in_range = sa.fillet_kt(0.1, 5.0)       # r/t = 0.02, below 0.05
    assert in_range is False
    assert kt == pytest.approx(2.45)


def test_metrics_match_independent_hand_calculation():
    """Regression baseline, hand-computed from the fixture:

    I = 1314.6 mm^4, c = 9.60 mm, M = 20 N * 80 mm = 1600 N*mm
    sigma_nom = 1600 * 9.60 / 1314.6 = 11.68 MPa, Kt(r/t=0.6) = 1.348
    bolt arm = |22 - 8| = 14 mm, bolt force = 1600 / 14 = 114.3 N
    net area = (30 - 5) * 5 = 125 mm^2, Kt_hole(5/30) = 2.579
    volume = 80*30*5 + 40*30*5 + 80*8*3 = 19 920 mm^3
    """
    m = _manifest()
    mets, _ = sa.metrics(m, _defaults(m))
    assert mets["mass_g"] == pytest.approx(24.70, rel=2e-3)
    assert mets["tip_deflection_mm"] == pytest.approx(0.7505, rel=2e-3)
    assert mets["stress_max_mpa"] == pytest.approx(15.75, rel=2e-3)
    assert mets["stress_hole_mpa"] == pytest.approx(2.358, rel=2e-3)
    assert mets["safety_factor"] == pytest.approx(3.17, rel=2e-3)


def test_deflection_bending_term_dominates_but_shear_is_included():
    m = _manifest()
    p = _defaults(m)
    mets, _ = sa.metrics(m, p)
    inertia, _ = sa.section_properties(30.0, 5.0, 8.0, 3.0)
    eb_only = 20.0 * 80.0 ** 3 / (3.0 * 3500.0 * inertia)
    assert mets["tip_deflection_mm"] > eb_only, "shear term must add to the deflection"
    assert mets["tip_deflection_mm"] < 1.03 * eb_only, "shear should be a small correction here"


def test_cad_volume_overrides_the_analytic_volume():
    m = _manifest()
    p = _defaults(m)
    analytic, notes_a = sa.metrics(m, p)
    measured, notes_m = sa.metrics(m, p, cad_volume_mm3=25000.0)
    assert measured["mass_g"] == pytest.approx(25000.0 * 1240.0 * 1e-6, rel=1e-9)
    assert measured["mass_g"] != analytic["mass_g"]
    assert any("analytic volume" in n for n in notes_a)
    assert not any("analytic volume" in n for n in notes_m)


# ------------------------------------------------------------- fail closed

def test_unconfirmed_material_blocks():
    m = _manifest()
    m.material.confirmed = False
    assert "material" in [q.id for q in sa.validate_manifest(m)]
    with pytest.raises(sa.ManifestNotReady):
        sa.metrics(m, _defaults(m))


def test_missing_load_blocks():
    m = _manifest()
    m.load_cases = []
    ids = [q.id for q in sa.validate_manifest(m)]
    assert "load" in ids and "fixtures" in ids
    with pytest.raises(sa.ManifestNotReady):
        sa.metrics(m, _defaults(m))


def test_unconfirmed_load_blocks_even_when_present():
    m = _manifest()
    m.load_cases[0].confirmed = False
    assert "load" in [q.id for q in sa.validate_manifest(m)]


def test_single_mounting_hole_blocks_because_there_is_no_couple_arm():
    m = _manifest()
    m.protected = [p for p in m.protected if p.id != "mount_hole_b"]
    assert "mount_geometry" in [q.id for q in sa.validate_manifest(m)]


def test_coincident_mounting_holes_block_rather_than_dividing_by_zero():
    m = _manifest()
    for p in m.protected:
        if p.id == "mount_hole_b":
            p.nominal = dict(p.nominal, z=8.0)      # same place as mount_hole_a
    assert "mount_spacing" in [q.id for q in sa.validate_manifest(m)]
    with pytest.raises(sa.ManifestNotReady):
        sa.metrics(m, _defaults(m))


def test_zero_bending_load_blocks():
    m = _manifest()
    m.load_cases[0].vector_n = [10.0, 0.0, 0.0]
    with pytest.raises(sa.ManifestNotReady):
        sa.metrics(m, _defaults(m))


def test_axial_component_is_flagged_not_silently_dropped():
    m = _manifest()
    m.load_cases[0].vector_n = [15.0, -20.0, 0.0]
    _, notes = sa.metrics(m, _defaults(m))
    assert any("axial" in n for n in notes)


def test_stress_past_yield_is_reported_not_clipped():
    """Safety rule 3: an invalid result is surfaced, never silently made valid."""
    m = _manifest()
    m.load_cases[0].vector_n = [0.0, -2000.0, 0.0]
    mets, notes = sa.metrics(m, _defaults(m))
    assert mets["safety_factor"] < 1.0
    assert mets["stress_max_mpa"] > m.material.yield_mpa
    assert any("exceeds yield" in n for n in notes)


def test_excessive_deflection_is_flagged():
    m = _manifest()
    m.load_cases[0].vector_n = [0.0, -600.0, 0.0]
    _, notes = sa.metrics(m, _defaults(m))
    assert any("small-deflection" in n for n in notes)


def test_convergence_check_cannot_pass_for_a_closed_form_model():
    """passed=None blocks; returning True would claim a check that never ran."""
    m = _manifest()
    res = sa.convergence_check(m, _defaults(m), "whatever.stl")
    assert res.passed is None
    assert "closed-form" in res.detail


def test_verification_fidelity_is_refused():
    m = _manifest()
    with pytest.raises(ValueError):
        sa.evaluate(m, _defaults(m), _goal(), fidelity="verification")


def test_capability_declares_screening_only_and_process_safe():
    cap = sa.capability()
    assert cap.fidelity == ["screening"]
    assert cap.process_safe is True
    assert cap.domain == "static_structural"
    assert "material" in cap.required_fields
    assert set(cap.metrics) == {m.name for m in sa.metric_catalog()}


# ------------------------------------------------------------- sensitivity

def _mets(m, **over):
    p = _defaults(m)
    p.update(over)
    return sa.metrics(m, p)[0]


def test_thicker_flange_is_stiffer_stronger_and_heavier():
    m = _manifest()
    thin, thick = _mets(m, thickness=3.0), _mets(m, thickness=7.0)
    assert thick["tip_deflection_mm"] < thin["tip_deflection_mm"]
    assert thick["stress_max_mpa"] < thin["stress_max_mpa"]
    assert thick["mass_g"] > thin["mass_g"]
    assert thick["safety_factor"] > thin["safety_factor"]


def test_longer_flange_deflects_more_and_is_more_stressed():
    m = _manifest()
    short, long_ = _mets(m, flange_length=50.0), _mets(m, flange_length=110.0)
    assert long_["tip_deflection_mm"] > short["tip_deflection_mm"]
    assert long_["stress_max_mpa"] > short["stress_max_mpa"]


def test_taller_rib_is_stiffer_for_little_mass():
    m = _manifest()
    none, tall = _mets(m, rib_height=0.0), _mets(m, rib_height=18.0)
    assert tall["tip_deflection_mm"] < none["tip_deflection_mm"]
    assert tall["mass_g"] > none["mass_g"]
    # The rib is the efficient way to add stiffness: large deflection win per gram.
    d_stiff = (none["tip_deflection_mm"] - tall["tip_deflection_mm"]) / none["tip_deflection_mm"]
    d_mass = (tall["mass_g"] - none["mass_g"]) / none["mass_g"]
    assert d_stiff > d_mass


def test_lightening_holes_trade_mass_against_hole_stress():
    """The tradeoff the judge is meant to see in five seconds."""
    m = _manifest()
    solid, holed = _mets(m, lightening_holes=0), _mets(m, lightening_holes=3)
    assert holed["mass_g"] < solid["mass_g"]
    assert holed["stress_hole_mpa"] > solid["stress_hole_mpa"]
    assert holed["safety_factor"] <= solid["safety_factor"]


def test_bigger_fillet_lowers_the_root_concentration():
    m = _manifest()
    sharp, round_ = _mets(m, fillet_radius=1.0), _mets(m, fillet_radius=8.0)
    assert round_["stress_max_mpa"] < sharp["stress_max_mpa"]


def test_evaluation_is_deterministic():
    m = _manifest()
    a = sa.metrics(m, _defaults(m))[0]
    b = sa.metrics(m, _defaults(m))[0]
    assert a == b

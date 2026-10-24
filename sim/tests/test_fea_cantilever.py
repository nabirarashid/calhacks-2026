"""G-2 / G-3: validate the FEA candidate against Euler-Bernoulli. No network.

These are the gate tests from PLAN.md C.2 and the first half of the P3-B3
golden suite. If the solver is not installed they skip with a clear reason,
but the gate laptop must run them.
"""
import pytest

pytest.importorskip("skfem", reason="FEA candidate (b) scikit-fem is not installed")

from sim.fea import skfem_elastic as fe   # noqa: E402

# Cantilever, rectangular section, L/h = 10 (PLAN C.2 G-2 requires >= 10).
L, B, H = 100.0, 10.0, 10.0
E_MPA, NU, LOAD_N = 70000.0, 0.33, 100.0

# Element choice is part of the verdict, not an implementation detail:
# linear tets lock in bending and must never be used for the structural domain.
GATE_CELL, GATE_ORDER, GATE_GRID = "tet", 2, (12, 2, 2)


def _solve(grid, cell=GATE_CELL, order=GATE_ORDER):
    nx, ny, nz = grid
    return fe.solve_box_cantilever(L, B, H, E_MPA, NU, LOAD_N, nx, ny, nz,
                                   cell=cell, order=order)


def test_g2_tip_deflection_within_5_percent():
    want = fe.eb_tip_deflection(L, B, H, E_MPA, LOAD_N)
    got = _solve(GATE_GRID)["tip_deflection_mm"]
    err = abs(got - want) / want
    assert err < 0.05, "tip deflection %.5f vs EB %.5f (%.2f %%)" % (got, want, 100 * err)


def test_g2_bending_stress_at_midspan_within_10_percent():
    """Read stress at x = L/2, away from both the clamp and the load patch."""
    want = fe.eb_bending_stress(L, B, H, LOAD_N, L / 2.0)
    res = _solve(GATE_GRID)
    got = fe.extreme_fibre_sxx(res, L / 2.0, H, x_tol_mm=L / (2 * GATE_GRID[0]))
    err = abs(got - want) / want
    assert err < 0.10, "sigma_xx %.2f vs EB %.2f MPa (%.2f %%)" % (got, want, 100 * err)


def test_g3_mesh_refinement_changes_deflection_under_3_percent():
    coarse = _solve((12, 2, 2))["tip_deflection_mm"]
    fine = _solve((20, 2, 2))["tip_deflection_mm"]
    change = abs(fine - coarse) / coarse
    assert change < 0.03, "refinement moved deflection %.2f %% (%.5f -> %.5f)" % (
        100 * change, coarse, fine)


def test_deflection_converges_from_below_toward_timoshenko():
    """Displacement-based FE is stiff, so refinement must increase deflection
    and approach the shear-corrected value rather than overshoot it."""
    eb = fe.eb_tip_deflection(L, B, H, E_MPA, LOAD_N)
    timo = fe.timoshenko_tip_deflection(L, B, H, E_MPA, NU, LOAD_N)
    assert timo > eb
    coarse = _solve((8, 2, 2))["tip_deflection_mm"]
    fine = _solve((20, 2, 2))["tip_deflection_mm"]
    assert coarse < fine <= timo * 1.02, "%.5f -> %.5f, timoshenko %.5f" % (
        coarse, fine, timo)


def test_linear_tets_are_unacceptably_stiff():
    """Guard against regressing to ElementTetP1.

    P1 tets lock in bending: they under-predict deflection by tens of percent
    and still converge smoothly, so a refinement check alone would not catch
    it. This is exactly the 'plausible wrong number' safety rule 3 forbids, so
    the failure is pinned here deliberately.
    """
    want = fe.eb_tip_deflection(L, B, H, E_MPA, LOAD_N)
    got = _solve((20, 2, 2), cell="tet", order=1)["tip_deflection_mm"]
    err = (want - got) / want
    assert err > 0.20, (
        "P1 tets were expected to be >20 %% too stiff but were off by %.2f %%; "
        "re-check the element choice before trusting this" % (100 * err))


def test_thicker_section_deflects_less():
    """Sensitivity direction required by P3-B3."""
    thin = fe.solve_box_cantilever(L, B, 8.0, E_MPA, NU, LOAD_N, 12, 2, 2,
                                   cell=GATE_CELL, order=GATE_ORDER)
    thick = fe.solve_box_cantilever(L, B, 12.0, E_MPA, NU, LOAD_N, 12, 2, 2,
                                    cell=GATE_CELL, order=GATE_ORDER)
    assert thick["tip_deflection_mm"] < thin["tip_deflection_mm"]

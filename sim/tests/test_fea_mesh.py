"""STL -> tet mesh tests (W-B). Fast by default; the full plate solve is opt-in.

The slow test reproduces the measured result that two quadratic tets through
the wall match plate theory to ~3 %. It takes ~40 s, so it runs only with
DARWIN_SLOW_FEA=1, but the gate laptop should run it.
"""
import os

import numpy as np
import pytest

pytest.importorskip("gmsh", reason="gmsh is not installed")
pytest.importorskip("skfem", reason="scikit-fem is not installed")

from shared import fin_geometry          # noqa: E402
from sim.fea import mesh as M            # noqa: E402

RECT = {"root_chord": 90.0, "taper_ratio": 1.0, "semi_span": 60.0,
        "sweep_deg": 0.0, "thickness": 3.0, "edge_profile": "square"}
SWEPT = {"root_chord": 90.0, "taper_ratio": 0.5, "semi_span": 60.0,
         "sweep_deg": 30.0, "thickness": 3.0, "edge_profile": "square"}


def _stl(tmp_path, params, name):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as fh:
        fh.write(fin_geometry.prism_stl(params))
    return path


@pytest.mark.parametrize("params", [RECT, SWEPT], ids=["rectangular", "swept"])
def test_reconstructed_volume_matches_the_part(tmp_path, params):
    """If the solid is not the exported part, every downstream number is wrong."""
    stl = _stl(tmp_path, params, "p.stl")
    meshed = M.mesh_stl(stl, 3.0)
    ok, frac = M.volume_agrees_with(meshed, fin_geometry.derived(params)["volume_mm3"])
    assert ok, "mesh volume off by %.3f %%" % (100 * frac)
    assert frac < 1e-6


def test_mesh_has_tets_and_consistent_indices(tmp_path):
    meshed = M.mesh_stl(_stl(tmp_path, RECT, "r.stl"), 3.0)
    assert meshed["n_tets"] > 0 and meshed["n_nodes"] > 0
    assert meshed["tets"].shape[0] == 4
    assert int(meshed["tets"].min()) == 0
    assert int(meshed["tets"].max()) == meshed["n_nodes"] - 1


def test_meshing_is_fast(tmp_path):
    """Meshing is not the bottleneck; the solve is."""
    meshed = M.mesh_stl(_stl(tmp_path, RECT, "r.stl"), 2.0)
    assert meshed["elapsed_s"] < 5.0


def test_refinement_levels_rebuild_and_get_finer(tmp_path):
    """Rebuilding per level is deliberate: mesh.clear() then generate(3) on an
    STL-derived model hangs forever (measured). This test passing at all is the
    regression guard for that."""
    levels = M.refinement_levels(_stl(tmp_path, RECT, "r.stl"), 3.0, ratio=0.65, levels=2)
    assert len(levels) == 2
    assert levels[1]["n_nodes"] > levels[0]["n_nodes"]
    assert levels[1]["target_h_mm"] < levels[0]["target_h_mm"]


def test_to_skfem_gives_contiguous_arrays(tmp_path):
    sk = M.to_skfem(M.mesh_stl(_stl(tmp_path, RECT, "r.stl"), 3.0))
    assert sk.p.flags["C_CONTIGUOUS"] and sk.t.flags["C_CONTIGUOUS"]


def test_wall_sizing_is_two_elements_through_thickness():
    assert M.h_for_wall(4.0) == pytest.approx(2.0)
    assert M.h_for_wall(3.0, elements=3) == pytest.approx(1.0)
    with pytest.raises(M.MeshingError):
        M.h_for_wall(0.0)


def test_dof_estimate_is_calibrated_at_its_anchor():
    assert M.estimate_p2_dofs(16200.0, 1.5) == pytest.approx(143550.0, rel=1e-9)


def test_dof_estimate_scales_with_volume_over_h_cubed():
    base = M.estimate_p2_dofs(16200.0, 2.0)
    assert M.estimate_p2_dofs(32400.0, 2.0) == pytest.approx(2.0 * base)
    assert M.estimate_p2_dofs(16200.0, 1.0) == pytest.approx(8.0 * base)


def test_thin_walls_decline_and_thick_walls_are_affordable():
    """The tension the demo has to respect: the optimizer minimises mass and so
    proposes thin designs, which are exactly the ones FEA cannot afford."""
    vol = 19900.0                                     # default bracket, analytic
    assert M.within_dof_budget(vol, 2.0)[0] is False
    assert M.within_dof_budget(vol, 3.0)[0] is False
    assert M.within_dof_budget(vol, 4.0)[0] is True
    assert M.within_dof_budget(vol, 5.0)[0] is True


def test_missing_stl_and_bad_size_raise(tmp_path):
    with pytest.raises(M.MeshingError):
        M.mesh_stl(os.path.join(str(tmp_path), "nope.stl"), 2.0)
    with pytest.raises(M.MeshingError):
        M.mesh_stl(_stl(tmp_path, RECT, "r.stl"), 0.0)


@pytest.mark.skipif(os.environ.get("DARWIN_SLOW_FEA") != "1",
                    reason="~40 s; set DARWIN_SLOW_FEA=1 (the gate laptop should)")
def test_full_chain_matches_plate_theory_with_two_elements_through_wall(tmp_path):
    """STL -> gmsh -> skfem P2 -> deflection, against the correct reference.

    The plate is wider (90) than it is long (60), so it bends as a plate with
    modulus E / (1 - nu^2), not as a beam. Against beam theory this same answer
    reads as -8.5 % and looks like a failure; against plate theory it is +2.7 %.
    """
    from sim.fea import skfem_elastic as fe
    stl = _stl(tmp_path, RECT, "r.stl")
    b, h, length = 90.0, 3.0, 60.0
    e_mpa, nu, force = 70000.0, 0.33, 100.0
    inertia = b * h ** 3 / 12.0
    plate = force * length ** 3 / (3.0 * (e_mpa / (1.0 - nu ** 2)) * inertia)

    meshed = M.mesh_stl(stl, M.h_for_wall(h))
    res = fe.solve_mesh_cantilever(M.to_skfem(meshed), e_mpa, nu,
                                   lambda x: x[2] < 1e-6,
                                   lambda x: x[2] > length - 1e-6,
                                   [0.0, -force, 0.0], order=2)
    got = abs(res["displacement_mm"][1])
    assert abs(got - plate) / plate < 0.05, "%.5f vs plate %.5f" % (got, plate)

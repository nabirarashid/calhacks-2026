"""STL surface -> tetrahedral volume mesh via gmsh (W-B, PLAN.md v3 B.2 sim/fea).

The CAD side gives us a triangulated surface, not a solid, so every FEA run
starts by reconstructing a meshable volume from an STL:

    merge -> classifySurfaces -> createGeometry -> addVolume -> generate(3)

`classifySurfaces(..., forReparametrization=True)` is what makes the discrete
surfaces re-meshable; without it `createGeometry` yields surfaces that cannot be
refined.

**Trap, measured on 2026-10-24.** Do NOT call `gmsh.model.mesh.clear()` and
re-run `generate(3)` to produce a second refinement level. On an STL-derived
model that hangs *indefinitely* — no exception, no timeout, just a frozen
process. Rebuilding the whole pipeline per level costs ~0.07 s for a plate, so
`refinement_levels()` always rebuilds. A hang has no recovery path at a demo.

Units are mm throughout.
"""
import math
import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

# gmsh's 3D algorithms: 1 = Delaunay, 10 = HXT (parallel, more robust on thin
# walls). Both meshed the test plate in well under a second; HXT is the default
# here because the bracket is also thin-walled.
ALGORITHM_DELAUNAY = 1
ALGORITHM_HXT = 10

DEFAULT_FEATURE_ANGLE_DEG = 40.0
DEFAULT_CURVE_ANGLE_DEG = 180.0


class GmshUnavailable(RuntimeError):
    """gmsh is not importable, so FEA cannot run (the caller must degrade)."""


class MeshingError(RuntimeError):
    """The STL could not be turned into a usable volume mesh."""


def _gmsh():
    try:
        import gmsh
    except Exception as exc:                      # pragma: no cover
        raise GmshUnavailable("gmsh is not available: %s" % exc)
    return gmsh


def _tet_volume_mm3(points: np.ndarray, tets: np.ndarray) -> float:
    """Sum of |det| / 6 over all tetrahedra."""
    a = points[:, tets[0]]
    b = points[:, tets[1]]
    c = points[:, tets[2]]
    d = points[:, tets[3]]
    return float(np.sum(np.abs(np.einsum("ij,ij->j", b - a, np.cross((c - a).T, (d - a).T).T))) / 6.0)


def mesh_stl(stl_path: str, target_h_mm: float, *,
             feature_angle_deg: float = DEFAULT_FEATURE_ANGLE_DEG,
             algorithm: int = ALGORITHM_HXT,
             optimize: bool = False,
             min_h_mm: Optional[float] = None) -> Dict[str, object]:
    """Reconstruct a volume from `stl_path` and mesh it with linear tets.

    Linear tets are correct *here*: the mesh carries the geometry, while the
    displacement field uses quadratic elements (ElementTetP2) on top of it.
    P1 tets as the *field* are 22-51 % too stiff in bending — see
    sim/FEA_SPIKE.md and test_fea_cantilever.py.

    Returns points (3, n), tets (4, m), counts, volume and timings.
    """
    if not os.path.exists(stl_path):
        raise MeshingError("no such STL: %s" % stl_path)
    if target_h_mm <= 0.0:
        raise MeshingError("target_h_mm must be positive")

    gmsh = _gmsh()
    started = time.time()
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.merge(stl_path)

        gmsh.model.mesh.classifySurfaces(
            math.radians(feature_angle_deg), True, True,
            math.radians(DEFAULT_CURVE_ANGLE_DEG))
        gmsh.model.mesh.createGeometry()

        surfaces = [s[1] for s in gmsh.model.getEntities(2)]
        if not surfaces:
            raise MeshingError("no surfaces survived classification; the STL may be "
                               "non-manifold or empty")
        loop = gmsh.model.geo.addSurfaceLoop(surfaces)
        gmsh.model.geo.addVolume([loop])
        gmsh.model.geo.synchronize()

        gmsh.option.setNumber("Mesh.MeshSizeMax", target_h_mm)
        if min_h_mm is not None:
            gmsh.option.setNumber("Mesh.MeshSizeMin", min_h_mm)
        gmsh.option.setNumber("Mesh.Algorithm3D", int(algorithm))
        gmsh.option.setNumber("Mesh.Optimize", 1 if optimize else 0)
        gmsh.option.setNumber("Mesh.OptimizeNetgen", 0)

        gmsh.model.mesh.generate(3)

        node_tags, coords, _ = gmsh.model.mesh.getNodes()
        if len(node_tags) == 0:
            raise MeshingError("mesh has no nodes")
        points = np.asarray(coords, dtype=float).reshape(-1, 3).T      # (3, n)

        # gmsh node tags are 1-based and may be sparse; map them to 0-based rows.
        index_of = np.zeros(int(node_tags.max()) + 1, dtype=np.int64)
        index_of[np.asarray(node_tags, dtype=np.int64)] = np.arange(len(node_tags))

        elem_types, _, elem_nodes = gmsh.model.mesh.getElements(3)
        tets = None
        for etype, enodes in zip(elem_types, elem_nodes):
            if int(etype) == 4:                   # 4 = 4-node tetrahedron
                tets = index_of[np.asarray(enodes, dtype=np.int64)].reshape(-1, 4).T
                break
        if tets is None or tets.shape[1] == 0:
            raise MeshingError("no tetrahedra were generated")

        volume = _tet_volume_mm3(points, tets)
        return {
            "points": points,
            "tets": tets,
            "n_nodes": int(points.shape[1]),
            "n_tets": int(tets.shape[1]),
            "volume_mm3": volume,
            "target_h_mm": float(target_h_mm),
            "algorithm": int(algorithm),
            "elapsed_s": time.time() - started,
        }
    finally:
        gmsh.finalize()


def to_skfem(meshed: Dict[str, object]):
    """Wrap the arrays as a skfem MeshTet (geometry only; the field order is
    chosen by the solver)."""
    try:
        from skfem import MeshTet
    except Exception as exc:                      # pragma: no cover
        raise GmshUnavailable("scikit-fem is not available: %s" % exc)
    # skfem copies non-contiguous arrays and warns; do it once here instead.
    return MeshTet(np.ascontiguousarray(meshed["points"], dtype=np.float64),
                   np.ascontiguousarray(meshed["tets"], dtype=np.int64))


def p2_dof_count(meshed: Dict[str, object]) -> int:
    """Exact vector-P2 dof count, so callers can respect the solve budget.

    sim/FEA_SPIKE.md measured ~9 s at 50k dofs and ~24 s at 100k, against a
    20 s budget, so keep a coarse bracket under about 60k.
    """
    from skfem import Basis, ElementTetP2, ElementVector
    mesh = to_skfem(meshed)
    return int(Basis(mesh, ElementVector(ElementTetP2())).N)


def refinement_levels(stl_path: str, coarse_h_mm: float, ratio: float = 0.65,
                      levels: int = 2, **kwargs) -> List[Dict[str, object]]:
    """Independent meshes at successively finer element size.

    Each level rebuilds from the STL. See the module docstring: reusing the
    model and calling `mesh.clear()` between levels hangs forever.
    """
    if levels < 1:
        raise MeshingError("levels must be >= 1")
    if not 0.0 < ratio < 1.0:
        raise MeshingError("ratio must be between 0 and 1")
    out = []
    h = float(coarse_h_mm)
    for _ in range(levels):
        out.append(mesh_stl(stl_path, h, **kwargs))
        h *= ratio
    return out


def volume_agrees_with(meshed: Dict[str, object], expected_mm3: float,
                       tol_frac: float = 0.03) -> Tuple[bool, float]:
    """Compare mesh volume with an independent expectation (CAD or analytic).

    A volume mismatch means the reconstructed solid is not the exported part —
    a leaked surface, a swallowed feature, or the wrong units.
    """
    if expected_mm3 <= 0.0:
        return False, float("inf")
    frac = abs(float(meshed["volume_mm3"]) - expected_mm3) / expected_mm3
    return frac <= tol_frac, frac


# ---- sizing rules, measured 2026-10-24 on a 90 x 60 x 3 mm plate ----
#
# Two quadratic tets through the wall is the threshold, not a preference:
#   h = t/1.0  -> -83 % deflection      (one element: it locks)
#   h = t/1.5  -> -85 %
#   h = t/2.0  -> +2.7 % of plate theory, and refining to t/2.5 moves it 0.2 %
# So h = t/2 is both necessary and sufficient. The cost is the problem: that
# plate needed 143k dofs and 40 s, against the 20 s G-4 budget.

ELEMENTS_THROUGH_WALL = 2
# Above this, decline the solve rather than return a locked or late answer.
DEFAULT_DOF_BUDGET = 80000


def h_for_wall(thickness_mm: float, elements: int = ELEMENTS_THROUGH_WALL) -> float:
    """Largest element size that still resolves bending through a thin wall."""
    if thickness_mm <= 0.0:
        raise MeshingError("thickness must be positive")
    return float(thickness_mm) / float(max(elements, 1))


def estimate_p2_dofs(volume_mm3: float, h_mm: float) -> float:
    """Rough vector-P2 dof count from volume and element size, for budgeting
    *before* meshing. `p2_dof_count` is exact once a mesh exists.

    Scaled from the measured plate (143 550 dofs at 16 200 mm^3, h = 1.5 mm) as
    volume / h^3. Measured accuracy: +5 % at h = 2.0, -15 % at h = 1.2, and it
    under-counts by ~1.7x at very coarse h where surface nodes dominate. Good
    enough to decide whether to attempt a solve; not a substitute for counting.
    """
    if h_mm <= 0.0:
        raise MeshingError("h_mm must be positive")
    return 143550.0 * (float(volume_mm3) / 16200.0) * ((1.5 / float(h_mm)) ** 3)


def within_dof_budget(volume_mm3: float, thickness_mm: float,
                      budget: int = DEFAULT_DOF_BUDGET) -> Tuple[bool, float, float]:
    """(affordable, required h, estimated dofs) for a wall of this thickness.

    A thin design is exactly what a mass-minimising optimizer proposes, and it
    is also the expensive one, so this is checked before meshing and the solve
    is declined rather than run late or run locked.
    """
    h = h_for_wall(thickness_mm)
    dofs = estimate_p2_dofs(volume_mm3, h)
    return dofs <= budget, h, dofs


__all__ = ["ALGORITHM_DELAUNAY", "ALGORITHM_HXT", "ELEMENTS_THROUGH_WALL",
           "DEFAULT_DOF_BUDGET", "GmshUnavailable", "MeshingError", "mesh_stl",
           "to_skfem", "p2_dof_count", "refinement_levels", "volume_agrees_with",
           "h_for_wall", "estimate_p2_dofs", "within_dof_budget"]

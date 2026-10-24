"""Linear-elastic solve on a structured hex mesh (FEA candidate b: scikit-fem).

Units are mm / N / MPa throughout, so E is in MPa, I in mm^4 and displacement
in mm. This module is the G-2/G-3 spike and the basis of
`structural_fea_v1`'s solve step; it owns no physics decisions.
"""
from typing import Dict, Optional, Tuple

import numpy as np
from skfem import (Basis, ElementHex1, ElementHex2, ElementTetP1, ElementTetP2,
                   ElementVector, FacetBasis, LinearForm, MeshHex, MeshTet, asm,
                   condense, solve)
from skfem.helpers import sym_grad, trace
from skfem.models.elasticity import lame_parameters, linear_elasticity

EPS = 1e-9


# Trilinear hexes and linear tets both lock in bending, so the element order is
# a first-class knob: the bracket is meshed with tets, where P1 is far too stiff.
_ELEMENTS = {
    ("hex", 1): ElementHex1,
    ("hex", 2): ElementHex2,
    ("tet", 1): ElementTetP1,
    ("tet", 2): ElementTetP2,
}
_MESHES = {"hex": MeshHex, "tet": MeshTet}


def _vector_element(cell: str = "hex", order: int = 1):
    try:
        return ElementVector(_ELEMENTS[(cell, order)]())
    except KeyError:
        raise ValueError("unsupported element: %s order %s" % (cell, order))


def solve_box_cantilever(length_mm: float, width_mm: float, height_mm: float,
                         e_mpa: float, nu: float, load_n: float,
                         nx: int, ny: int, nz: int,
                         cell: str = "hex", order: int = 1) -> Dict[str, object]:
    """Cantilever box fixed at x=0, uniform -z traction on the x=L face.

    Returns tip deflection, the sigma_xx field and its quadrature coordinates.
    """
    mesh = _MESHES[cell].init_tensor(
        np.linspace(0.0, length_mm, nx + 1),
        np.linspace(0.0, width_mm, ny + 1),
        np.linspace(0.0, height_mm, nz + 1),
    )
    element = _vector_element(cell, order)
    basis = Basis(mesh, element)

    lam, mu = lame_parameters(e_mpa, nu)
    stiffness = asm(linear_elasticity(lam, mu), basis)

    # Traction so that the total applied force equals load_n.
    traction = load_n / (width_mm * height_mm)

    tip_facets = mesh.facets_satisfying(lambda x: x[0] > length_mm - EPS)
    tip_basis = FacetBasis(mesh, element, facets=tip_facets)

    @LinearForm
    def body(v, w):
        return -traction * v[2]

    rhs = asm(body, tip_basis)

    clamped = basis.get_dofs(lambda x: x[0] < EPS)
    disp = solve(*condense(stiffness, rhs, D=clamped))

    # Tip deflection: mean -w over nodes on the loaded face, which is the
    # beam-theory quantity (a single corner node picks up local Poisson effects).
    nodal = disp[basis.nodal_dofs]                     # (3, n_nodes)
    on_tip = mesh.p[0] > length_mm - EPS
    tip_deflection = float(-np.mean(nodal[2][on_tip]))

    field = basis.interpolate(disp)
    eps = sym_grad(field)
    sxx = 2.0 * mu * eps[0, 0] + lam * (eps[0, 0] + eps[1, 1] + eps[2, 2])
    coords = basis.global_coordinates()                # (3, nelems, nqp)

    return {
        "mesh": mesh,
        "basis": basis,
        "disp": disp,
        "tip_deflection_mm": tip_deflection,
        "sxx_mpa": np.asarray(sxx),
        "coords_mm": np.asarray(coords),
        "n_dofs": int(basis.N),
        "n_elements": int(mesh.t.shape[1]),
    }


def extreme_fibre_sxx(result: Dict[str, object], x_mm: float, height_mm: float,
                      x_tol_mm: float, fibre_frac: float = 0.25) -> float:
    """Peak |sigma_xx| near a chord station, restricted to the outer fibres.

    Mid-thickness material carries almost no bending stress, so averaging over
    the section would understate the beam-theory value; only the outer fibres
    are comparable to M*y/I.
    """
    coords = result["coords_mm"]
    sxx = result["sxx_mpa"]
    x = coords[0]
    z = coords[2]
    near_station = np.abs(x - x_mm) <= x_tol_mm
    outer = (z <= fibre_frac * height_mm) | (z >= (1.0 - fibre_frac) * height_mm)
    mask = near_station & outer
    if not mask.any():
        raise ValueError("no quadrature points near x=%.3f" % x_mm)
    return float(np.max(np.abs(sxx[mask])))


# ---- analytic references (Euler-Bernoulli, the thing we validate against) ----

def eb_second_moment(width_mm: float, height_mm: float) -> float:
    return width_mm * height_mm ** 3 / 12.0


def eb_tip_deflection(length_mm: float, width_mm: float, height_mm: float,
                      e_mpa: float, load_n: float) -> float:
    """delta = P L^3 / (3 E I)."""
    inertia = eb_second_moment(width_mm, height_mm)
    return load_n * length_mm ** 3 / (3.0 * e_mpa * inertia)


def eb_bending_stress(length_mm: float, width_mm: float, height_mm: float,
                      load_n: float, x_mm: float) -> float:
    """sigma = M(x) * (h/2) / I with M(x) = P (L - x) for a tip load."""
    inertia = eb_second_moment(width_mm, height_mm)
    moment = load_n * (length_mm - x_mm)
    return moment * (height_mm / 2.0) / inertia


def timoshenko_tip_deflection(length_mm: float, width_mm: float, height_mm: float,
                              e_mpa: float, nu: float, load_n: float) -> float:
    """Euler-Bernoulli plus the shear term, for reporting only.

    At L/h = 10 shear adds under 1 %, so a 3D solve landing slightly above the
    Euler-Bernoulli value is expected rather than an error.
    """
    bending = eb_tip_deflection(length_mm, width_mm, height_mm, e_mpa, load_n)
    g_mpa = e_mpa / (2.0 * (1.0 + nu))
    area = width_mm * height_mm
    kappa = 5.0 / 6.0
    return bending + load_n * length_mm / (kappa * g_mpa * area)

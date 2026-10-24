"""fin_v1 analytic geometry — FROZEN at CP0. The spec is fin_geometry.md.

Shared by S1 (STL sanity check), S2 (mass/planform), the mocks, and mirrored
in dashboard/src/geometry/finPreview.ts. All lengths in mm, angles in degrees.
"""
import math
from typing import Dict, List

from shared.contracts import ParamValue

# Cross-section area removed per unit edge length, as a multiple of t^2.
ROUNDED_REMOVAL_T2 = 0.5 - math.pi / 8.0     # full round r = t/2: t*r - pi*r^2/2, r = t/2


def derived(params: Dict[str, ParamValue]) -> Dict[str, float]:
    """Planform quantities for one fin. Keys:
    c_r, c_t, s, sweep_rad, t, x_tip_le, x_tip_te, area_mm2, mac_mm, le_len_mm,
    te_len_mm, tip_len_mm, aft_overhang_mm, bevel_mm, volume_mm3.
    """
    c_r = float(params["root_chord"])
    lam = float(params["taper_ratio"])
    s = float(params["semi_span"])
    sweep = math.radians(float(params["sweep_deg"]))
    t = float(params["thickness"])
    profile = str(params.get("edge_profile", "square"))

    c_t = c_r * lam
    x_tip_le = s * math.tan(sweep)
    x_tip_te = x_tip_le + c_t
    area = s * (c_r + c_t) / 2.0
    mac = (2.0 / 3.0) * c_r * (1 + lam + lam * lam) / (1 + lam)
    le_len = s / math.cos(sweep)
    te_len = math.hypot(s, x_tip_te - c_r)
    tip_len = c_t
    bevel = min(3.0 * t, 0.25 * c_t)

    if profile == "rounded":            # LE + tip edges, square TE
        removed = ROUNDED_REMOVAL_T2 * t * t * (le_len + tip_len)
    elif profile == "beveled":          # symmetric chamfer to a sharp edge on LE + TE
        removed = 0.5 * bevel * t * (le_len + te_len)
    else:                               # square
        removed = 0.0

    return {
        "c_r": c_r, "c_t": c_t, "s": s, "sweep_rad": sweep, "t": t,
        "x_tip_le": x_tip_le, "x_tip_te": x_tip_te,
        "area_mm2": area, "mac_mm": mac,
        "le_len_mm": le_len, "te_len_mm": te_len, "tip_len_mm": tip_len,
        "aft_overhang_mm": max(0.0, x_tip_te - c_r),
        "bevel_mm": bevel if profile == "beveled" else 0.0,
        "volume_mm3": area * t - removed,
    }


def bbox_mm(params: Dict[str, ParamValue]) -> List[float]:
    """[xmin, ymin, zmin, xmax, ymax, zmax] in the Onshape frame (x chord, y thickness, z span)."""
    d = derived(params)
    return [min(0.0, d["x_tip_le"]), -d["t"] / 2.0, 0.0,
            max(d["c_r"], d["x_tip_te"]), d["t"] / 2.0, d["s"]]


def planform_corners(params: Dict[str, ParamValue]) -> List[List[float]]:
    """(x, z) corners: root LE, root TE, tip TE, tip LE (counter-clockwise seen from +y)."""
    d = derived(params)
    return [[0.0, 0.0], [d["c_r"], 0.0], [d["x_tip_te"], d["s"]], [d["x_tip_le"], d["s"]]]


def prism_stl(params: Dict[str, ParamValue], name: str = "fin") -> str:
    """ASCII STL of the square-edged plate (12 triangles). Used by fake_cad and tests."""
    d = derived(params)
    h = d["t"] / 2.0
    q = planform_corners(params)
    bot = [(x, -h, z) for x, z in q]
    top = [(x, h, z) for x, z in q]
    tris = [
        (bot[0], bot[2], bot[1]), (bot[0], bot[3], bot[2]),     # -y face
        (top[0], top[1], top[2]), (top[0], top[2], top[3]),     # +y face
    ]
    for i in range(4):
        j = (i + 1) % 4
        tris.append((bot[i], bot[j], top[j]))
        tris.append((bot[i], top[j], top[i]))
    lines = ["solid %s" % name]
    for a, c, b in tris:                # (a, c, b): outward normals, positive signed volume
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        mag = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
        lines.append("  facet normal %.6e %.6e %.6e" % (n[0] / mag, n[1] / mag, n[2] / mag))
        lines.append("    outer loop")
        for p in (a, b, c):
            lines.append("      vertex %.6e %.6e %.6e" % p)
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid %s" % name)
    return "\n".join(lines) + "\n"

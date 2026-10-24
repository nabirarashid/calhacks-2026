"""Mass properties for the frozen ``fin_v1`` geometry.

All public lengths are millimetres and masses are grams.  Geometry is delegated
to :mod:`shared.fin_geometry` so CAD, simulation, and the dashboard use the
same edge-removal convention.
"""
from dataclasses import dataclass
from typing import Dict, Mapping, Union

from shared import fin_geometry
from shared.contracts import ParamValue

ContextValue = Union[float, str]


@dataclass(frozen=True)
class MassResult:
    """Mass and centroid of the complete fin set."""

    volume_mm3: float
    fin_mass_g: float
    fin_mass_total_g: float
    fin_centroid_mm: float
    cg_mm: float


def planform_centroid_x_mm(params: Mapping[str, ParamValue]) -> float:
    """Return one fin's chordwise centroid measured from its root leading edge.

    This is the area centroid of the swept trapezoid.  Because thickness is
    symmetric and uniform, it is also the mass centroid used by the reduced
    order CG model.  Small centroid shifts caused by edge treatments are
    intentionally ignored, matching the frozen analytic geometry model.
    """

    d = fin_geometry.derived(dict(params))
    c_r = d["c_r"]
    c_t = d["c_t"]
    denominator = 3.0 * (c_r + c_t)
    if denominator <= 0.0:
        raise ValueError("root and tip chord must have a positive sum")
    return (
        c_r * c_r
        + c_r * c_t
        + c_t * c_t
        + d["x_tip_le"] * (c_r + 2.0 * c_t)
    ) / denominator


def mass_properties(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> MassResult:
    """Calculate fin mass and the rocket CG including the complete fin set."""

    d = fin_geometry.derived(dict(params))
    density_g_cm3 = float(context.get("density_g_cm3", 1.24))
    fin_count = int(params.get("fin_count", 4))
    if density_g_cm3 <= 0.0:
        raise ValueError("density_g_cm3 must be positive")
    if fin_count <= 0:
        raise ValueError("fin_count must be positive")

    volume_mm3 = max(0.0, d["volume_mm3"])
    fin_mass_g = volume_mm3 / 1000.0 * density_g_cm3
    total_mass_g = fin_mass_g * fin_count

    body_length_mm = float(context["body_length_mm"])
    root_le_mm = body_length_mm - d["c_r"]
    fin_centroid_mm = root_le_mm + planform_centroid_x_mm(params)

    dry_mass_g = float(context["mass_without_fins_g"])
    dry_cg_mm = float(context["cg_without_fins_mm"])
    if dry_mass_g <= 0.0:
        raise ValueError("mass_without_fins_g must be positive")
    cg_mm = (
        dry_mass_g * dry_cg_mm + total_mass_g * fin_centroid_mm
    ) / (dry_mass_g + total_mass_g)

    return MassResult(
        volume_mm3=volume_mm3,
        fin_mass_g=fin_mass_g,
        fin_mass_total_g=total_mass_g,
        fin_centroid_mm=fin_centroid_mm,
        cg_mm=cg_mm,
    )


def mass_metrics(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> Dict[str, float]:
    """Return the mass-related entries in the frozen metric catalog."""

    result = mass_properties(params, context)
    return {
        "fin_mass_g": result.fin_mass_g,
        "fin_mass_total_g": result.fin_mass_total_g,
        "cg_mm": result.cg_mm,
    }

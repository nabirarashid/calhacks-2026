"""Barrowman normal-force and center-of-pressure model for ``fin_v1``.

Barrowman owns the stability result.  Aerodynamic drag is deliberately kept in
``sim.aero`` so disagreement between the two reduced-order models is visible
rather than tuned away.
"""
import math
from dataclasses import dataclass
from typing import Dict, Mapping, Union

from shared import fin_geometry
from shared.contracts import ParamValue

from sim.mass import mass_properties

ContextValue = Union[float, str]


@dataclass(frozen=True)
class BarrowmanResult:
    cp_mm: float
    cg_mm: float
    stability_margin_cal: float
    cn_alpha_fins: float
    fin_cp_mm: float
    nose_cp_mm: float
    fin_body_interference: float
    mid_chord_length_mm: float


def fin_normal_force_slope(
    params: Mapping[str, ParamValue], body_diameter_mm: float
) -> float:
    """Return the complete fin set's ``CN_alpha`` in ``1/rad``."""

    d = fin_geometry.derived(dict(params))
    fin_count = int(params.get("fin_count", 4))
    if body_diameter_mm <= 0.0:
        raise ValueError("body_diameter_mm must be positive")
    if fin_count <= 0:
        raise ValueError("fin_count must be positive")

    body_radius_mm = body_diameter_mm / 2.0
    mid_chord_dx_mm = d["x_tip_le"] + d["c_t"] / 2.0 - d["c_r"] / 2.0
    mid_chord_length_mm = math.hypot(d["s"], mid_chord_dx_mm)
    interference = 1.0 + body_radius_mm / (d["s"] + body_radius_mm)
    denominator = 1.0 + math.sqrt(
        1.0 + (2.0 * mid_chord_length_mm / (d["c_r"] + d["c_t"])) ** 2
    )
    return (
        interference
        * 4.0
        * fin_count
        * (d["s"] / body_diameter_mm) ** 2
        / denominator
    )


def fin_center_of_pressure_mm(
    params: Mapping[str, ParamValue], body_length_mm: float
) -> float:
    """Return fin CP from the rocket nose tip using the standard X_f form."""

    d = fin_geometry.derived(dict(params))
    chord_sum = d["c_r"] + d["c_t"]
    if chord_sum <= 0.0:
        raise ValueError("root and tip chord must have a positive sum")

    root_le_mm = body_length_mm - d["c_r"]
    sweep_term = d["x_tip_le"] * (d["c_r"] + 2.0 * d["c_t"]) / (
        3.0 * chord_sum
    )
    chord_term = (chord_sum - d["c_r"] * d["c_t"] / chord_sum) / 6.0
    return root_le_mm + sweep_term + chord_term


def stability(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> BarrowmanResult:
    """Evaluate nose-plus-fin CP and the mass-coupled stability margin."""

    d = fin_geometry.derived(dict(params))
    body_diameter_mm = float(context["body_diameter_mm"])
    body_length_mm = float(context["body_length_mm"])
    nose_length_mm = float(context["nose_length_mm"])
    if body_diameter_mm <= 0.0 or nose_length_mm <= 0.0:
        raise ValueError("body diameter and nose length must be positive")

    fin_cn_alpha = fin_normal_force_slope(params, body_diameter_mm)
    fin_cp_mm = fin_center_of_pressure_mm(params, body_length_mm)

    # Tangent-ogive approximation from the frozen plan.
    nose_cn_alpha = 2.0
    nose_cp_mm = 0.466 * nose_length_mm
    cp_mm = (
        nose_cn_alpha * nose_cp_mm + fin_cn_alpha * fin_cp_mm
    ) / (nose_cn_alpha + fin_cn_alpha)

    mass = mass_properties(params, context)
    stability_margin_cal = (cp_mm - mass.cg_mm) / body_diameter_mm

    body_radius_mm = body_diameter_mm / 2.0
    mid_chord_dx_mm = d["x_tip_le"] + d["c_t"] / 2.0 - d["c_r"] / 2.0
    mid_chord_length_mm = math.hypot(d["s"], mid_chord_dx_mm)
    interference = 1.0 + body_radius_mm / (d["s"] + body_radius_mm)
    return BarrowmanResult(
        cp_mm=cp_mm,
        cg_mm=mass.cg_mm,
        stability_margin_cal=stability_margin_cal,
        cn_alpha_fins=fin_cn_alpha,
        fin_cp_mm=fin_cp_mm,
        nose_cp_mm=nose_cp_mm,
        fin_body_interference=interference,
        mid_chord_length_mm=mid_chord_length_mm,
    )


def stability_metrics(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> Dict[str, float]:
    """Return the Barrowman-owned entries in the frozen metric catalog."""

    result = stability(params, context)
    return {
        "stability_margin_cal": result.stability_margin_cal,
        "cp_mm": result.cp_mm,
        "cg_mm": result.cg_mm,
        "cn_alpha_fins": result.cn_alpha_fins,
    }

"""Screening-level NACA TN 4197-style fin flutter estimate."""
import math
from dataclasses import dataclass
from typing import Dict, Mapping, Union

from shared import fin_geometry
from shared.contracts import ParamValue

ContextValue = Union[float, str]

SEA_LEVEL_PRESSURE_PA = 101325.0
SEA_LEVEL_SPEED_OF_SOUND_MPS = 340.3


@dataclass(frozen=True)
class FlutterResult:
    flutter_velocity_mps: float
    flutter_margin: float
    aspect_ratio: float


def flutter_boundary(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> FlutterResult:
    """Return the isotropic-material flutter screening boundary.

    Shear modulus and pressure are both converted to pascals.  The aspect ratio
    is the frozen full-pair definition ``(2s)^2 / (2A)``.
    """

    d = fin_geometry.derived(dict(params))
    area_mm2 = d["area_mm2"]
    if area_mm2 <= 0.0 or d["c_r"] <= 0.0 or d["t"] <= 0.0:
        raise ValueError("fin area, root chord, and thickness must be positive")

    aspect_ratio = 2.0 * d["s"] ** 2 / area_mm2
    taper_ratio = d["c_t"] / d["c_r"]
    thickness_ratio = d["t"] / d["c_r"]
    shear_modulus_pa = float(context.get("shear_modulus_gpa", 1.3)) * 1.0e9
    design_velocity_mps = float(context["design_velocity_mps"])
    if shear_modulus_pa <= 0.0 or design_velocity_mps <= 0.0:
        raise ValueError("shear modulus and design velocity must be positive")

    denominator = (
        1.337
        * aspect_ratio ** 3
        * SEA_LEVEL_PRESSURE_PA
        * (taper_ratio + 1.0)
    ) / (2.0 * (aspect_ratio + 2.0) * thickness_ratio ** 3)
    flutter_velocity_mps = SEA_LEVEL_SPEED_OF_SOUND_MPS * math.sqrt(
        shear_modulus_pa / denominator
    )
    return FlutterResult(
        flutter_velocity_mps=flutter_velocity_mps,
        flutter_margin=flutter_velocity_mps / design_velocity_mps,
        aspect_ratio=aspect_ratio,
    )


def flutter_metrics(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> Dict[str, float]:
    """Return the flutter entries in the frozen metric catalog."""

    result = flutter_boundary(params, context)
    return {
        "flutter_velocity_mps": result.flutter_velocity_mps,
        "flutter_margin": result.flutter_margin,
    }

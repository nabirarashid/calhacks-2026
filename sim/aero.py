"""Fin aerodynamics using AeroSandbox 4.2.8 with an analytic fallback.

The AeroSandbox dependency is optional at import time so the rest of Darwin can
still run in constrained demo environments.  Every fallback is explicit in the
returned warnings; results remain deterministic and no network access occurs.
"""
import math
import os
import warnings as python_warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple, Union

from shared import fin_geometry
from shared.contracts import ParamValue

ContextValue = Union[float, str]

INTERFERENCE_FACTOR = 1.10

# Hoerner-style pressure/base-drag multipliers applied to projected edge area
# t*s. A square edge exposes a blunt leading edge and trailing base, a rounded
# profile only retains the trailing base, and a beveled profile adds neither.
EDGE_PRESSURE_COEFFICIENT = {
    "square": 1.29,
    "rounded": 0.12,
    "beveled": 0.0,
}


@dataclass(frozen=True)
class AeroResult:
    drag_n: float
    cd_fins: float
    cd_one_fin: float
    cn_alpha_one_fin: float
    reference_cn_alpha_one_fin: float
    dynamic_pressure_pa: float
    reynolds: float
    method: str
    linearity_error_pct: float = 0.0
    warnings: Tuple[str, ...] = ()


_ASB = None  # type: Optional[Any]
_ASB_IMPORT_ATTEMPTED = False


def _load_aerosandbox() -> Optional[Any]:
    global _ASB, _ASB_IMPORT_ATTEMPTED
    if not _ASB_IMPORT_ATTEMPTED:
        _ASB_IMPORT_ATTEMPTED = True
        try:
            # Keep Matplotlib's import cache inside Darwin's ignored runtime
            # directory rather than touching the user's home directory.
            runtime_cache = Path(__file__).resolve().parent.parent / ".darwin" / "matplotlib"
            os.environ.setdefault("MPLCONFIGDIR", str(runtime_cache))
            with python_warnings.catch_warnings():
                python_warnings.filterwarnings(
                    "ignore", category=DeprecationWarning, module="matplotlib.*"
                )
                import aerosandbox as asb  # type: ignore

            _ASB = asb
        except (ImportError, OSError):
            _ASB = None
    return _ASB


def aerosandbox_available() -> bool:
    """Return whether the pinned AeroSandbox runtime can be imported."""

    return _load_aerosandbox() is not None


def rectangular_reference_lift_slope(
    params: Mapping[str, ParamValue], context: Mapping[str, ContextValue]
) -> float:
    """Return mirrored-pair AeroBuildup CL-alpha for validation tests.

    The production fast path intentionally models one physical fin.  This
    reference calculation supplies an aerodynamic symmetry plane so a simple
    rectangular case can be compared directly with finite-wing theory.
    """
    asb = _load_aerosandbox()
    if asb is None:
        raise RuntimeError("AeroSandbox is unavailable")
    velocity_mps = float(context["design_velocity_mps"])
    altitude_m = float(context.get("altitude_m", 0.0))
    alpha_deg = float(context.get("alpha_deg", 2.0))
    if abs(alpha_deg) < 1.0e-9:
        raise ValueError("alpha_deg must be nonzero for lift-slope evaluation")
    airplane = _build_airplane(asb, params, mirrored=True)
    atmosphere = asb.Atmosphere(altitude=altitude_m)
    with python_warnings.catch_warnings():
        python_warnings.filterwarnings(
            "ignore", category=RuntimeWarning, module="neuralfoil\\.main"
        )
        zero = asb.AeroBuildup(
            airplane=airplane,
            op_point=asb.OperatingPoint(
                atmosphere=atmosphere, velocity=velocity_mps, alpha=0.0
            ),
        ).run()
        at_alpha = asb.AeroBuildup(
            airplane=airplane,
            op_point=asb.OperatingPoint(
                atmosphere=atmosphere,
                velocity=velocity_mps,
                alpha=alpha_deg,
            ),
        ).run()
    return abs(
        (_scalar(at_alpha["CL"]) - _scalar(zero["CL"]))
        / math.radians(alpha_deg)
    )


def _isa_properties(altitude_m: float) -> Tuple[float, float, float]:
    """Density, speed of sound, and kinematic viscosity in the troposphere."""

    altitude_m = max(-500.0, min(11000.0, altitude_m))
    temperature_k = 288.15 - 0.0065 * altitude_m
    pressure_pa = 101325.0 * (temperature_k / 288.15) ** 5.255877
    density = pressure_pa / (287.05287 * temperature_k)
    speed_of_sound = math.sqrt(1.4 * 287.05287 * temperature_k)
    dynamic_viscosity = (
        1.716e-5
        * (temperature_k / 273.15) ** 1.5
        * (273.15 + 110.4)
        / (temperature_k + 110.4)
    )
    return density, speed_of_sound, dynamic_viscosity / density


def profile_drag_adjustment(params: Mapping[str, ParamValue]) -> float:
    """Return edge pressure-drag increment referenced to one fin's area."""

    d = fin_geometry.derived(dict(params))
    profile = str(params.get("edge_profile", "square"))
    coefficient = EDGE_PRESSURE_COEFFICIENT.get(profile)
    if coefficient is None:
        raise ValueError("unsupported edge_profile: %s" % profile)
    return coefficient * d["t"] * d["s"] / d["area_mm2"]


def _analytic_coefficients(
    params: Mapping[str, ParamValue], velocity_mps: float, altitude_m: float
) -> Tuple[float, float, float, float]:
    """Return CD, half-wing CN-alpha, q, and Reynolds for fallback scoring."""

    d = fin_geometry.derived(dict(params))
    density, _speed_of_sound, kinematic_viscosity = _isa_properties(altitude_m)
    mac_m = d["mac_mm"] / 1000.0
    reynolds = max(velocity_mps * mac_m / kinematic_viscosity, 1.0e4)

    # Schlichting turbulent flat-plate correlation.  It is intentionally a
    # smooth screening fallback rather than an attempt to impersonate CFD.
    skin_friction = 0.455 / math.log10(reynolds) ** 2.58
    thickness_ratio = d["t"] / d["mac_mm"]
    form_factor = 1.0 + 2.0 * thickness_ratio + 60.0 * thickness_ratio ** 4
    cd_one_fin = 2.0 * skin_friction * form_factor + profile_drag_adjustment(params)

    # Full fin-pair AR from the frozen geometry. A physical fin is one half of
    # that pair, so its lift-slope contribution is half the lifting-line value.
    aspect_ratio = 2.0 * d["s"] ** 2 / d["area_mm2"]
    cn_alpha_one_fin = math.pi * aspect_ratio / (aspect_ratio + 2.0)
    dynamic_pressure_pa = 0.5 * density * velocity_mps ** 2
    return cd_one_fin, cn_alpha_one_fin, dynamic_pressure_pa, reynolds


def _scalar(value: Any) -> float:
    """Convert AeroSandbox/CasADi/NumPy scalar-shaped output to ``float``."""

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return float(item())
        except (TypeError, ValueError):
            pass
    try:
        return float(value[0])
    except (TypeError, ValueError, IndexError, KeyError):
        return float(value)


def _build_airplane(
    asb: Any, params: Mapping[str, ParamValue], mirrored: bool = False
) -> Any:
    d = fin_geometry.derived(dict(params))
    thickness_percent = int(round(100.0 * max(0.02, d["t"] / d["mac_mm"])))
    thickness_percent = max(2, min(40, thickness_percent))
    airfoil = asb.Airfoil(name="naca00%02d" % thickness_percent)

    # AeroSandbox works in metres and defines lifting-surface span along y.
    # Map the frozen geometry's radial z coordinate onto aerodynamic y; leaving
    # it on z would make alpha a roll about the fin plane and produce zero lift.
    # The fast empirical buildup models one physical fin.  The high-fidelity
    # lifting-line check requests a mirrored pair to supply its root symmetry
    # plane.  Doubling reference area in that case preserves the per-fin
    # coefficient used below.
    wing = asb.Wing(
        name="fin_v1_one_fin",
        symmetric=mirrored,
        xsecs=[
            asb.WingXSec(
                xyz_le=[0.0, 0.0, 0.0],
                chord=d["c_r"] / 1000.0,
                airfoil=airfoil,
            ),
            asb.WingXSec(
                xyz_le=[d["x_tip_le"] / 1000.0, d["s"] / 1000.0, 0.0],
                chord=d["c_t"] / 1000.0,
                airfoil=airfoil,
            ),
        ],
    )
    return asb.Airplane(
        name="fin_v1",
        xyz_ref=[0.0, 0.0, 0.0],
        wings=[wing],
        s_ref=(2.0 if mirrored else 1.0) * d["area_mm2"] / 1.0e6,
        c_ref=d["mac_mm"] / 1000.0,
        b_ref=2.0 * d["s"] / 1000.0,
    )


def _run_aerosandbox(
    asb: Any,
    params: Mapping[str, ParamValue],
    velocity_mps: float,
    altitude_m: float,
    alpha_deg: float,
    high_fidelity: bool,
) -> Tuple[float, float, float, float, float]:
    """Return CD, chosen slope, density, linearity error, and buildup slope."""

    airplane = _build_airplane(asb, params, mirrored=high_fidelity)
    atmosphere = asb.Atmosphere(altitude=altitude_m)
    op_zero = asb.OperatingPoint(
        atmosphere=atmosphere, velocity=velocity_mps, alpha=0.0
    )
    op_alpha = asb.OperatingPoint(
        atmosphere=atmosphere, velocity=velocity_mps, alpha=alpha_deg
    )
    with python_warnings.catch_warnings():
        python_warnings.filterwarnings(
            "ignore", message=".*Conversion of an array with ndim > 0.*"
        )
        python_warnings.filterwarnings(
            "ignore", category=RuntimeWarning, module="neuralfoil\\.main"
        )
        if high_fidelity:
            # VLM is inviscid, so retain AeroBuildup's profile drag and add the
            # VLM induced increment at the configured incidence.  A small alpha
            # sweep independently checks whether the linear lift assumption is
            # valid for the champion.
            drag_zero = asb.AeroBuildup(
                airplane=airplane, op_point=op_zero
            ).run()
            buildup_at_alpha = asb.AeroBuildup(
                airplane=airplane, op_point=op_alpha
            ).run()
            buildup_slope = (
                _scalar(buildup_at_alpha["CL"]) - _scalar(drag_zero["CL"])
            ) / math.radians(alpha_deg)
            sweep_degrees = [-4.0, -2.0, 0.0, 2.0, 4.0, 6.0]
            sweep_results = []
            for sweep_alpha in sweep_degrees:
                sweep_op = asb.OperatingPoint(
                    atmosphere=atmosphere,
                    velocity=velocity_mps,
                    alpha=sweep_alpha,
                )
                sweep_results.append(
                    asb.VortexLatticeMethod(
                        airplane=airplane, op_point=sweep_op
                    ).run()
                )
            alpha_radians = [math.radians(value) for value in sweep_degrees]
            lift_values = [_scalar(value["CL"]) for value in sweep_results]
            alpha_mean = sum(alpha_radians) / len(alpha_radians)
            lift_mean = sum(lift_values) / len(lift_values)
            slope_denominator = sum(
                (value - alpha_mean) ** 2 for value in alpha_radians
            )
            cn_alpha = sum(
                (angle - alpha_mean) * (lift - lift_mean)
                for angle, lift in zip(alpha_radians, lift_values)
            ) / slope_denominator
            intercept = lift_mean - cn_alpha * alpha_mean
            lift_scale = max(max(abs(value) for value in lift_values), 1.0e-9)
            linearity_error_pct = 100.0 * max(
                abs(lift - (intercept + cn_alpha * angle))
                for angle, lift in zip(alpha_radians, lift_values)
            ) / lift_scale

            zero_index = sweep_degrees.index(0.0)
            configured = asb.VortexLatticeMethod(
                airplane=airplane, op_point=op_alpha
            ).run()
            induced_increment = max(
                0.0,
                _scalar(configured["CD"])
                - _scalar(sweep_results[zero_index]["CD"]),
            )
            cd_base = _scalar(drag_zero["CD"]) + induced_increment
        else:
            zero = asb.AeroBuildup(airplane=airplane, op_point=op_zero).run()
            at_alpha = asb.AeroBuildup(
                airplane=airplane, op_point=op_alpha
            ).run()
            cd_base = _scalar(zero["CD"])
            alpha_rad = math.radians(alpha_deg)
            if abs(alpha_rad) < 1.0e-9:
                raise ValueError("alpha_deg must be nonzero for lift-slope evaluation")
            cn_alpha = (_scalar(at_alpha["CL"]) - _scalar(zero["CL"])) / alpha_rad
            buildup_slope = cn_alpha
            linearity_error_pct = 0.0

    density = _scalar(atmosphere.density())
    if not math.isfinite(cd_base) or not 0.0 < cd_base < 0.5:
        raise ValueError("AeroSandbox returned an implausible drag coefficient")
    if not math.isfinite(cn_alpha) or not 0.05 < abs(cn_alpha) < 20.0:
        raise ValueError("AeroSandbox returned an implausible lift slope")
    return (
        cd_base,
        abs(cn_alpha),
        density,
        linearity_error_pct,
        abs(buildup_slope),
    )


def aero_metrics(
    params: Mapping[str, ParamValue],
    context: Mapping[str, ContextValue],
    high_fidelity: bool = False,
) -> AeroResult:
    """Evaluate fin-set drag and a one-fin lift-slope cross-check.

    ``drag_n`` includes every physical fin and the frozen 1.1 body-interference
    multiplier. ``cd_fins`` is referenced to the rocket body cross-section.
    """

    d = fin_geometry.derived(dict(params))
    velocity_mps = float(context["design_velocity_mps"])
    altitude_m = float(context.get("altitude_m", 0.0))
    alpha_deg = float(context.get("alpha_deg", 2.0))
    fin_count = int(params.get("fin_count", 4))
    body_diameter_m = float(context["body_diameter_mm"]) / 1000.0
    if velocity_mps <= 0.0 or body_diameter_m <= 0.0 or fin_count <= 0:
        raise ValueError("velocity, body diameter, and fin count must be positive")
    if abs(alpha_deg) < 1.0e-9:
        alpha_deg = 2.0

    analytic_cd, analytic_slope, analytic_q, reynolds = _analytic_coefficients(
        params, velocity_mps, altitude_m
    )
    method = "analytic_fallback"
    linearity_error_pct = 0.0
    warning_messages = []
    cd_one_fin = analytic_cd
    cn_alpha_one_fin = analytic_slope
    reference_cn_alpha_one_fin = analytic_slope
    dynamic_pressure_pa = analytic_q

    asb = _load_aerosandbox()
    if asb is None:
        warning_messages.append("AeroSandbox unavailable; analytic drag fallback used")
    else:
        try:
            (
                base_cd,
                cn_alpha_one_fin,
                density,
                linearity_error_pct,
                reference_cn_alpha_one_fin,
            ) = _run_aerosandbox(
                asb,
                params,
                velocity_mps,
                altitude_m,
                alpha_deg,
                high_fidelity,
            )
            cd_one_fin = base_cd + profile_drag_adjustment(params)
            dynamic_pressure_pa = 0.5 * density * velocity_mps ** 2
            method = "aerosandbox_vlm" if high_fidelity else "aerosandbox_aerobuildup"
            if high_fidelity and linearity_error_pct > 10.0:
                warning_messages.append(
                    "VLM alpha-sweep nonlinearity is %.1f %%" % linearity_error_pct
                )
        except Exception as exc:  # solver errors must degrade to a scored design
            warning_messages.append(
                "AeroSandbox %s failed (%s); analytic fallback used"
                % ("VLM" if high_fidelity else "AeroBuildup", type(exc).__name__)
            )

    fin_area_m2 = d["area_mm2"] / 1.0e6
    drag_n = (
        cd_one_fin
        * dynamic_pressure_pa
        * fin_area_m2
        * fin_count
        * INTERFERENCE_FACTOR
    )
    body_reference_area_m2 = math.pi * (body_diameter_m / 2.0) ** 2
    cd_fins = drag_n / (dynamic_pressure_pa * body_reference_area_m2)
    return AeroResult(
        drag_n=drag_n,
        cd_fins=cd_fins,
        cd_one_fin=cd_one_fin,
        cn_alpha_one_fin=cn_alpha_one_fin,
        reference_cn_alpha_one_fin=reference_cn_alpha_one_fin,
        dynamic_pressure_pa=dynamic_pressure_pa,
        reynolds=reynolds,
        method=method,
        linearity_error_pct=linearity_error_pct,
        warnings=tuple(warning_messages),
    )


def warm_up() -> AeroResult:
    """Warm AeroSandbox caches explicitly; safe for process-pool initializers."""

    params = {
        "root_chord": 90.0,
        "taper_ratio": 0.5,
        "semi_span": 60.0,
        "sweep_deg": 30.0,
        "thickness": 3.0,
        "edge_profile": "rounded",
        "fin_count": 4,
    }
    context = {
        "body_diameter_mm": 76.2,
        "design_velocity_mps": 120.0,
        "altitude_m": 0.0,
        "alpha_deg": 2.0,
    }
    return aero_metrics(params, context)

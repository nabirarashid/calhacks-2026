"""Physics scorer for the frozen trapezoidal rocket-fin design space."""
from typing import Dict, List, Mapping, Optional, Union
import math

from shared import fin_geometry
from shared.contracts import DesignSpace, Goal, MetricInfo, ParamValue

from sim.aero import AeroResult, aero_metrics
from sim.barrowman import BarrowmanResult, stability
from sim.flutter import flutter_boundary
from sim.mass import MassResult, mass_properties
from sim.plugins import PluginEvaluation, ScorerPlugin

ContextValue = Union[float, str]


def _catalog() -> List[MetricInfo]:
    """Construct the frozen catalog with fresh Pydantic objects."""

    return [
        MetricInfo(
            name="stability_margin_cal",
            unit="cal",
            description="(CP - CG) / body diameter, CG including fin mass",
            better="target",
            typical_min=0.0,
            typical_max=4.0,
            default_tolerance=0.75,
            default_target=2.0,
        ),
        MetricInfo(
            name="cp_mm",
            unit="mm",
            description="Barrowman center of pressure from the nose tip",
            better="info",
            typical_min=800.0,
            typical_max=1150.0,
        ),
        MetricInfo(
            name="cg_mm",
            unit="mm",
            description="Center of gravity from the nose tip, including fins",
            better="info",
            typical_min=650.0,
            typical_max=900.0,
        ),
        MetricInfo(
            name="drag_n",
            unit="N",
            description="Fin-set drag at design velocity (all fins)",
            better="lower",
            # Square edges (the only profile the live Part Studio builds) put fin-set drag at
            # 3-22 N over the design space (600-sample LHS, median 9 N). The old 0.2-4.0 N
            # range left drag_n scoring 0 for ~98 % of designs, so "keep drag low" had no signal.
            typical_min=1.0,
            typical_max=20.0,
        ),
        MetricInfo(
            name="cd_fins",
            unit="",
            description="Fin-set drag coefficient referenced to body cross-section",
            better="lower",
            typical_min=0.01,
            typical_max=0.25,
        ),
        MetricInfo(
            name="fin_mass_g",
            unit="g",
            description="Mass of one fin, solid PLA",
            better="lower",
            typical_min=3.0,
            typical_max=50.0,
        ),
        MetricInfo(
            name="fin_mass_total_g",
            unit="g",
            description="Mass of all fins",
            better="lower",
            typical_min=10.0,
            typical_max=200.0,
        ),
        MetricInfo(
            name="flutter_velocity_mps",
            unit="m/s",
            description="NACA TN 4197-style flutter boundary (screening estimate)",
            better="higher",
            typical_min=50.0,
            typical_max=600.0,
        ),
        MetricInfo(
            name="flutter_margin",
            unit="",
            description="Flutter velocity / design velocity",
            better="higher",
            typical_min=0.5,
            typical_max=5.0,
        ),
        MetricInfo(
            name="cn_alpha_fins",
            unit="1/rad",
            description="Barrowman fin normal-force slope with body interference",
            better="info",
            typical_min=2.0,
            typical_max=20.0,
        ),
        MetricInfo(
            name="aft_overhang_mm",
            unit="mm",
            description="Tip trailing edge behind the root trailing edge",
            better="lower",
            typical_min=0.0,
            typical_max=80.0,
        ),
        MetricInfo(
            name="planform_area_cm2",
            unit="cm^2",
            description="Planform area of one fin",
            better="info",
            typical_min=10.0,
            typical_max=110.0,
        ),
    ]


class FinV1Scorer:
    """Pure deterministic implementation of the ``fin_v1`` scorer plugin."""

    scorer_id = "fin_v1"

    def metric_catalog(self) -> List[MetricInfo]:
        return _catalog()

    @staticmethod
    def _context(
        space: DesignSpace, goal: Optional[Goal]
    ) -> Dict[str, ContextValue]:
        context = dict(space.context)
        if goal is not None:
            context.update(goal.context_overrides)
        return context

    @staticmethod
    def _plausibility_warnings(
        params: Mapping[str, ParamValue],
        context: Mapping[str, ContextValue],
        aero: AeroResult,
        barrowman: BarrowmanResult,
        mass: MassResult,
    ) -> List[str]:
        out = list(aero.warnings)
        if not 0.002 <= aero.cd_one_fin <= 0.2:
            out.append(
                "Fin-area drag coefficient %.4f is outside [0.002, 0.2]"
                % aero.cd_one_fin
            )
        if not -2.0 <= barrowman.stability_margin_cal <= 8.0:
            out.append(
                "Stability margin %.3f cal is outside [-2, 8]"
                % barrowman.stability_margin_cal
            )

        d = fin_geometry.derived(dict(params))
        expected_mass_g = (
            d["volume_mm3"]
            / 1000.0
            * float(context.get("density_g_cm3", 1.24))
        )
        tolerance_g = max(1.0e-9, abs(expected_mass_g) * 1.0e-9)
        if abs(mass.fin_mass_g - expected_mass_g) > tolerance_g:
            out.append("Fin mass is inconsistent with analytic volume x density")

        fin_count = int(params.get("fin_count", 4))
        if barrowman.cn_alpha_fins > 0.0:
            body_radius_m = float(context["body_diameter_mm"]) / 2000.0
            body_reference_area_m2 = math.pi * body_radius_m ** 2
            fin_area_m2 = d["area_mm2"] / 1.0e6
            # AeroSandbox's CL uses one-fin planform area; Barrowman's CN uses
            # the rocket body cross-section. Convert before comparing slopes.
            aero_set_body_reference = (
                aero.cn_alpha_one_fin
                * fin_count
                * fin_area_m2
                / body_reference_area_m2
            )
            slope_ratio = (
                aero_set_body_reference / barrowman.cn_alpha_fins
            )
            if not 0.6 <= slope_ratio <= 1.6:
                out.append(
                    "AeroSandbox/Barrowman lift-slope ratio %.2f is outside [0.6, 1.6]"
                    % slope_ratio
                )
        return out

    def evaluate_metrics(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
        fidelity: str = "fast",
    ) -> PluginEvaluation:
        if space.scorer != self.scorer_id:
            raise ValueError(
                "FinV1Scorer cannot score design space %r with scorer %r"
                % (space.id, space.scorer)
            )
        if fidelity not in ("fast", "high"):
            raise ValueError("fidelity must be 'fast' or 'high'")

        context = self._context(space, goal)
        d = fin_geometry.derived(dict(params))
        mass = mass_properties(params, context)
        barrowman = stability(params, context)
        flutter = flutter_boundary(params, context)
        aero = aero_metrics(params, context, high_fidelity=fidelity == "high")

        # Preserve frozen catalog order for stable JSON and bit-identical runs.
        metrics = {
            "stability_margin_cal": barrowman.stability_margin_cal,
            "cp_mm": barrowman.cp_mm,
            "cg_mm": barrowman.cg_mm,
            "drag_n": aero.drag_n,
            "cd_fins": aero.cd_fins,
            "fin_mass_g": mass.fin_mass_g,
            "fin_mass_total_g": mass.fin_mass_total_g,
            "flutter_velocity_mps": flutter.flutter_velocity_mps,
            "flutter_margin": flutter.flutter_margin,
            "cn_alpha_fins": barrowman.cn_alpha_fins,
            "aft_overhang_mm": d["aft_overhang_mm"],
            "planform_area_cm2": d["area_mm2"] / 100.0,
        }
        warnings = self._plausibility_warnings(
            params, context, aero, barrowman, mass
        )
        return PluginEvaluation(
            metrics=metrics,
            warnings=warnings,
            diagnostics={
                "aero_cn_alpha_one_fin": aero.cn_alpha_one_fin,
                "aero_reference_cn_alpha_one_fin": (
                    aero.reference_cn_alpha_one_fin
                ),
                "aero_linearity_error_pct": aero.linearity_error_pct,
            },
        )

    def metrics(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
    ) -> Dict[str, float]:
        return self.evaluate_metrics(space, params, goal).metrics

    def hifi(
        self,
        space: DesignSpace,
        params: Mapping[str, ParamValue],
        goal: Optional[Goal] = None,
    ) -> PluginEvaluation:
        fast = self.evaluate_metrics(space, params, goal, fidelity="fast")
        high = self.evaluate_metrics(space, params, goal, fidelity="high")
        warnings = list(high.warnings)
        fast_drag = fast.metrics["drag_n"]
        high_drag = high.metrics["drag_n"]
        drag_difference_pct = 0.0
        if fast_drag > 0.0:
            difference_pct = 100.0 * (high_drag - fast_drag) / fast_drag
            drag_difference_pct = difference_pct
            if abs(difference_pct) > 15.0:
                warnings.append(
                    "High-fidelity drag differs from fast model by %+.1f %%"
                    % difference_pct
                )
        fast_slope = high.diagnostics.get(
            "aero_reference_cn_alpha_one_fin", 0.0
        )
        high_slope = high.diagnostics.get("aero_cn_alpha_one_fin", 0.0)
        slope_difference_pct = (
            100.0 * (high_slope - fast_slope) / fast_slope
            if fast_slope > 0.0
            else 0.0
        )
        warnings.append(
            "High-fidelity cross-check: drag %+.1f %%, lift slope %+.1f %%, "
            "alpha-sweep nonlinearity %.1f %%"
            % (
                drag_difference_pct,
                slope_difference_pct,
                high.diagnostics.get("aero_linearity_error_pct", 0.0),
            )
        )
        return PluginEvaluation(
            metrics=high.metrics,
            warnings=warnings,
            diagnostics=high.diagnostics,
        )


PLUGIN: ScorerPlugin = FinV1Scorer()


def get_plugin() -> ScorerPlugin:
    return PLUGIN


def metric_catalog() -> List[MetricInfo]:
    return PLUGIN.metric_catalog()


def metrics(
    space: DesignSpace,
    params: Mapping[str, ParamValue],
    goal: Optional[Goal] = None,
) -> Dict[str, float]:
    return PLUGIN.metrics(space, params, goal)


def hifi(
    space: DesignSpace,
    params: Mapping[str, ParamValue],
    goal: Optional[Goal] = None,
) -> PluginEvaluation:
    return PLUGIN.hifi(space, params, goal)


__all__ = [
    "FinV1Scorer",
    "PLUGIN",
    "get_plugin",
    "hifi",
    "metric_catalog",
    "metrics",
]

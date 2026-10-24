"""Regenerate shared/fixtures/*.json (except sample_run.jsonl). Run: python -m shared.mocks.make_fixtures"""
import json
from pathlib import Path

from shared import fin_geometry
from shared.contracts import (
    BudgetStatus, CadSource, Constraint, DesignResult, DesignSpace, GeometryRef, Goal, MetricInfo,
    ModelBudget, Objective, OnshapeBudget, ParamSpec, Preset, Score, geometry_key, param_hash,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

FIN_SPACE = DesignSpace(
    id="fin_v1", name="Trapezoidal rocket fin", scorer="fin_v1",
    parameters=[
        ParamSpec(name="root_chord", kind="continuous", unit="mm", min=50, max=130, step=0.5, default=90.0,
                  cad_ref="root_chord", description="Chord at the body tube"),
        ParamSpec(name="taper_ratio", kind="continuous", unit="", min=0.2, max=1.0, step=0.01, default=0.5,
                  cad_ref="taper_ratio", description="Tip chord / root chord"),
        ParamSpec(name="semi_span", kind="continuous", unit="mm", min=30, max=90, step=0.5, default=60.0,
                  cad_ref="semi_span", description="Fin height from the body tube"),
        ParamSpec(name="sweep_deg", kind="continuous", unit="deg", min=0, max=60, step=0.5, default=30.0,
                  cad_ref="sweep_deg", description="Leading-edge sweep angle"),
        ParamSpec(name="thickness", kind="continuous", unit="mm", min=2.0, max=5.0, step=0.1, default=3.0,
                  cad_ref="thickness", description="Plate thickness"),
        ParamSpec(name="edge_profile", kind="choice", choices=["square", "rounded", "beveled"], default="rounded",
                  cad_ref="edge_profile", description="Leading/trailing edge treatment"),
        ParamSpec(name="fin_count", kind="integer", min=3, max=4, step=1, default=4, cad_driven=False,
                  description="Fins on the rocket (sim-only)"),
    ],
    context={"body_diameter_mm": 76.2, "body_length_mm": 1200.0, "nose_length_mm": 300.0,
             "nose_shape": "ogive", "mass_without_fins_g": 1500.0, "cg_without_fins_mm": 700.0,
             "design_velocity_mps": 120.0, "altitude_m": 0.0, "alpha_deg": 2.0,
             "material": "PLA", "density_g_cm3": 1.24, "shear_modulus_gpa": 1.3},
    source=CadSource(kind="onshape", doc_url=None, mode="configuration", model_revision="r1"),
)

FIN_METRICS = [
    MetricInfo(name="stability_margin_cal", unit="cal", better="target", typical_min=0.0, typical_max=4.0,
               default_target=2.0, default_tolerance=0.75,
               description="(CP - CG) / body diameter, CG including fin mass"),
    MetricInfo(name="cp_mm", unit="mm", better="info", typical_min=800.0, typical_max=1150.0,
               description="Barrowman center of pressure from the nose tip"),
    MetricInfo(name="cg_mm", unit="mm", better="info", typical_min=650.0, typical_max=900.0,
               description="Center of gravity from the nose tip, including fins"),
    MetricInfo(name="drag_n", unit="N", better="lower", typical_min=0.2, typical_max=4.0,
               description="Fin-set drag at design velocity (all fins)"),
    MetricInfo(name="cd_fins", unit="", better="lower", typical_min=0.01, typical_max=0.25,
               description="Fin-set drag coefficient referenced to body cross-section"),
    MetricInfo(name="fin_mass_g", unit="g", better="lower", typical_min=3.0, typical_max=50.0,
               description="Mass of one fin, solid PLA"),
    MetricInfo(name="fin_mass_total_g", unit="g", better="lower", typical_min=10.0, typical_max=200.0,
               description="Mass of all fins"),
    MetricInfo(name="flutter_velocity_mps", unit="m/s", better="higher", typical_min=50.0, typical_max=600.0,
               description="NACA TN 4197-style flutter boundary (screening estimate)"),
    MetricInfo(name="flutter_margin", unit="", better="higher", typical_min=0.5, typical_max=5.0,
               description="Flutter velocity / design velocity"),
    MetricInfo(name="cn_alpha_fins", unit="1/rad", better="info", typical_min=2.0, typical_max=20.0,
               description="Barrowman fin normal-force slope with body interference"),
    MetricInfo(name="aft_overhang_mm", unit="mm", better="lower", typical_min=0.0, typical_max=80.0,
               description="Tip trailing edge behind the root trailing edge"),
    MetricInfo(name="planform_area_cm2", unit="cm^2", better="info", typical_min=10.0, typical_max=110.0,
               description="Planform area of one fin"),
]

GOAL_EXAMPLE = Goal(
    source_text="Maximize this rocket fin's stability, keep drag low, keep it under 40 g, must fit a 3-inch body tube.",
    objectives=[
        Objective(metric="stability_margin_cal", direction="target", target=2.5, tolerance=1.0, weight=0.5),
        Objective(metric="drag_n", direction="minimize", weight=0.35),
        Objective(metric="fin_mass_total_g", direction="minimize", weight=0.15),
    ],
    constraints=[
        Constraint(ref="fin_mass_total_g", op="<=", value=40, hard=True, label="total fin mass <= 40 g"),
        Constraint(ref="flutter_margin", op=">=", value=1.5, hard=True, label="flutter-safe (default)"),
        Constraint(ref="stability_margin_cal", op=">=", value=1.0, hard=True, label="stable (default)"),
        Constraint(ref="aft_overhang_mm", op="<=", value=0, hard=False, label="no aft overhang"),
    ],
    context_overrides={"body_diameter_mm": 76.2},
    assumptions=["'Maximize stability' -> target 2.5 cal: beyond ~3 cal a rocket weathercocks",
                 "'under 40 g' read as the TOTAL for all fins", "3-inch tube = 76.2 mm body diameter"],
    parsed_by="llm",
)

EXAMPLE_PARAMS = {"root_chord": 92.0, "taper_ratio": 0.45, "semi_span": 62.0, "sweep_deg": 38.0,
                  "thickness": 2.4, "edge_profile": "beveled", "fin_count": 3}


def example_score() -> Score:
    d = fin_geometry.derived(EXAMPLE_PARAMS)
    mass = d["volume_mm3"] / 1000.0 * 1.24
    return Score(
        metrics={"stability_margin_cal": 2.31, "cp_mm": 1031.0, "cg_mm": 855.0, "drag_n": 1.31,
                 "cd_fins": 0.058, "fin_mass_g": round(mass, 2), "fin_mass_total_g": round(3 * mass, 2),
                 "flutter_velocity_mps": 205.0, "flutter_margin": 1.71, "cn_alpha_fins": 8.9,
                 "aft_overhang_mm": round(d["aft_overhang_mm"], 2),
                 "planform_area_cm2": round(d["area_mm2"] / 100.0, 2)},
        objective_scores={"stability_margin_cal": 0.81, "drag_n": 0.74, "fin_mass_total_g": 0.38},
        violations=[], feasible=True, aggregate=0.722, warnings=[], fidelity="fast", eval_ms=14.2,
    )


def example_design() -> DesignResult:
    gk = geometry_key(FIN_SPACE, EXAMPLE_PARAMS)
    d = fin_geometry.derived(EXAMPLE_PARAMS)
    return DesignResult(
        design_id="run_0712_3fa9-g03-a05", run_id="run_0712_3fa9", generation=3, origin="agent",
        params=EXAMPLE_PARAMS, param_hash=param_hash(FIN_SPACE, EXAMPLE_PARAMS),
        parent_ids=["run_0712_3fa9-g02-a01", "run_0712_3fa9-g02-a04"], operator="crossover",
        rationale="Take g02-a01's sweep (CP aft) with g02-a04's thin beveled section to cut mass; "
                  "3 fins keep total < 40 g.",
        score=example_score(), pareto_rank=0,
        geometry=GeometryRef(geometry_key=gk, status="ready", source="onshape_config",
                             stl_url="/api/geometry/%s.stl" % gk,
                             bbox_mm=[round(x, 2) for x in fin_geometry.bbox_mm(EXAMPLE_PARAMS)],
                             volume_mm3=round(d["volume_mm3"], 1), triangles=412, onshape_calls=1,
                             regen_status="OK", error=None, elapsed_ms=1710.0),
        timings_ms={"propose": 2900.0, "eval": 14.2, "geometry": 1710.0},
    )


BUDGET_EXAMPLE = BudgetStatus(
    onshape=OnshapeBudget(account_label="prod", calls_session=7, calls_ledger_total=212, remaining_estimate=2188,
                          reserve=400, reserve_unlocked=False, hard_stop=False,
                          last_synced_at="2026-10-24T09:05:00-07:00"),
    model=ModelBudget(provider="anthropic", calls_run=14, calls_cap_run=40, spend_run_usd=0.021,
                      spend_cap_run_usd=0.30, spend_total_usd=0.84, spend_cap_total_usd=4.50),
    evals_used=40, evals_budget=64,
)


PRESETS = [
    Preset(label="Stable & light", text=GOAL_EXAMPLE.source_text, goal=GOAL_EXAMPLE.model_copy(update={"parsed_by": "preset"})),
    Preset(label="Min drag @ 1.5 cal",
           text="Minimize drag while keeping at least 1.5 calibers of stability, and keep the fins flutter-safe.",
           goal=Goal(source_text="Minimize drag while keeping at least 1.5 calibers of stability, and keep the fins flutter-safe.",
                     objectives=[Objective(metric="drag_n", direction="minimize", weight=0.7),
                                 Objective(metric="stability_margin_cal", direction="target", target=1.75,
                                           tolerance=0.5, weight=0.3)],
                     constraints=[Constraint(ref="stability_margin_cal", op=">=", value=1.5, label="stability >= 1.5 cal"),
                                  Constraint(ref="flutter_margin", op=">=", value=1.5, label="flutter-safe (default)")],
                     assumptions=["'flutter-safe' -> flutter velocity >= 1.5 x design velocity"], parsed_by="preset")),
    Preset(label="Flutter-safe @ 200 m/s",
           text="Make the fins flutter-safe up to 200 m/s with a 2 caliber margin, as light as possible.",
           goal=Goal(source_text="Make the fins flutter-safe up to 200 m/s with a 2 caliber margin, as light as possible.",
                     objectives=[Objective(metric="stability_margin_cal", direction="target", target=2.0,
                                           tolerance=0.75, weight=0.4),
                                 Objective(metric="fin_mass_total_g", direction="minimize", weight=0.4),
                                 Objective(metric="drag_n", direction="minimize", weight=0.2)],
                     constraints=[Constraint(ref="flutter_margin", op=">=", value=1.5, label="flutter-safe at 200 m/s"),
                                  Constraint(ref="stability_margin_cal", op=">=", value=1.0, label="stable (default)")],
                     context_overrides={"design_velocity_mps": 200.0},
                     assumptions=["design velocity raised to 200 m/s for drag and flutter"], parsed_by="preset")),
]


def _dump(name: str, obj) -> None:
    path = FIXTURES / name
    if isinstance(obj, list):
        data = [o.model_dump(mode="json") for o in obj]
    else:
        data = obj.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("wrote", path.relative_to(FIXTURES.parent.parent))


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    _dump("design_space_fin.json", FIN_SPACE)
    _dump("metric_catalog_fin.json", FIN_METRICS)
    _dump("goal_example.json", GOAL_EXAMPLE)
    _dump("score_example.json", example_score())
    _dump("design_result_example.json", example_design())
    _dump("budget_example.json", BUDGET_EXAMPLE)
    _dump("presets.json", PRESETS)


if __name__ == "__main__":
    main()

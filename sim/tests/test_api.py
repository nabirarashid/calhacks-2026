"""Contract tests for the public deterministic simulation API."""

import json
import math
from pathlib import Path

import pytest

from shared.contracts import (
    DesignSpace,
    Goal,
    MetricInfo,
    Objective,
    Score,
    canonicalize,
)
from sim.api import (
    evaluate,
    evaluate_batch,
    metric_catalog,
    register_scorer,
    validate_high_fidelity,
)
from sim.plugins import PluginEvaluation


FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"
SPACE = DesignSpace.model_validate_json(
    (FIXTURES / "design_space_fin.json").read_text(encoding="utf-8")
)
GOAL = Goal.model_validate_json(
    (FIXTURES / "goal_example.json").read_text(encoding="utf-8")
)
CATALOG_DATA = json.loads(
    (FIXTURES / "metric_catalog_fin.json").read_text(encoding="utf-8")
)
CATALOG_NAMES = [item["name"] for item in CATALOG_DATA]


def _without_timing(score: Score):
    return score.model_dump(exclude={"eval_ms"})


def test_metric_catalog_exactly_matches_frozen_fixture_and_is_defensive() -> None:
    first = metric_catalog("fin_v1")
    assert [item.model_dump() for item in first] == CATALOG_DATA

    first[0].description = "mutated by caller"
    second = metric_catalog("fin_v1")
    assert second[0].description == CATALOG_DATA[0]["description"]
    assert second[0] is not first[0]


def test_evaluate_canonicalizes_and_returns_complete_metric_contract() -> None:
    raw = {
        "root_chord": 91.26,
        "semi_span": 500.0,
        "fin_count": 3.4,
        "edge_profile": "beveled",
    }
    canonical = canonicalize(SPACE, raw)
    from_raw = evaluate(SPACE, raw, GOAL)
    from_canonical = evaluate(SPACE, canonical, GOAL)

    assert list(from_raw.metrics) == CATALOG_NAMES
    assert _without_timing(from_raw) == _without_timing(from_canonical)
    assert set(from_raw.objective_scores) == {
        objective.metric for objective in GOAL.objectives
    }
    assert math.isfinite(from_raw.aggregate)
    assert from_raw.aggregate <= 1.0


def test_aggregate_matches_frozen_rule_for_feasible_and_infeasible_designs() -> None:
    feasible_params = {
        "root_chord": 50.0,
        "taper_ratio": 0.58,
        "semi_span": 68.0,
        "sweep_deg": 46.0,
        "thickness": 3.9,
        "edge_profile": "beveled",
        "fin_count": 4,
    }
    feasible = evaluate(SPACE, feasible_params, GOAL)
    assert feasible.feasible
    weighted = sum(
        objective.weight * feasible.objective_scores[objective.metric]
        for objective in GOAL.objectives
    ) / sum(objective.weight for objective in GOAL.objectives)
    soft_penalty = 0.1 * sum(
        violation.amount for violation in feasible.violations if not violation.hard
    )
    assert feasible.aggregate == pytest.approx(weighted - soft_penalty)

    infeasible = evaluate(SPACE, {}, GOAL)
    assert not infeasible.feasible
    hard = sum(violation.amount for violation in infeasible.violations if violation.hard)
    soft = sum(violation.amount for violation in infeasible.violations if not violation.hard)
    assert infeasible.aggregate == pytest.approx(-hard - 0.1 * soft)
    assert infeasible.aggregate < feasible.aggregate


def test_batch_preserves_input_order_and_matches_serial_evaluation() -> None:
    candidates = [
        {"root_chord": 90.0},
        {"root_chord": 50.0},
        {"root_chord": 130.0},
    ]
    batch = evaluate_batch(SPACE, candidates, GOAL, workers=0)
    serial = [evaluate(SPACE, params, GOAL) for params in candidates]

    assert [score.metrics["planform_area_cm2"] for score in batch] == pytest.approx(
        [40.5, 22.5, 58.5]
    )
    assert [_without_timing(score) for score in batch] == [
        _without_timing(score) for score in serial
    ]
    assert evaluate_batch(SPACE, [], GOAL, workers=0) == []


def test_repeated_evaluation_is_deterministic_except_elapsed_time() -> None:
    params = canonicalize(SPACE, {"root_chord": 73.5, "edge_profile": "square"})
    first = evaluate(SPACE, params, GOAL)
    second = evaluate(SPACE, params, GOAL)
    assert _without_timing(first) == _without_timing(second)


@pytest.mark.parametrize(
    "params, message",
    [
        ({"not_a_parameter": 1.0}, "unknown parameter"),
        ({"edge_profile": "serrated"}, "invalid choice"),
        ({"thickness": float("nan")}, "non-finite"),
    ],
)
def test_evaluate_rejects_invalid_parameters(params, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate(SPACE, params, GOAL)


def test_api_rejects_invalid_fidelity_workers_goal_and_scorer() -> None:
    with pytest.raises(ValueError, match="fidelity"):
        evaluate(SPACE, {}, GOAL, fidelity="cfd")
    with pytest.raises(ValueError, match="workers"):
        evaluate_batch(SPACE, [{}], GOAL, workers=-1)

    invalid_goal = GOAL.model_copy(
        update={
            "objectives": [
                Objective(metric="missing_metric", direction="maximize", weight=1.0)
            ]
        }
    )
    with pytest.raises(ValueError, match="unknown metric"):
        evaluate(SPACE, {}, invalid_goal)

    unknown_space = SPACE.model_copy(update={"scorer": "not_registered"})
    with pytest.raises(KeyError, match="unknown scorer"):
        evaluate(unknown_space, {}, GOAL)


class _NoMethods:
    pass


class _CatalogOnly:
    @staticmethod
    def metric_catalog():
        return []


class _TinyPlugin:
    @staticmethod
    def metric_catalog():
        return [
            MetricInfo(
                name="synthetic",
                unit="",
                description="test-only metric",
                better="higher",
                typical_min=50.0,
                typical_max=130.0,
            )
        ]

    @staticmethod
    def evaluate_metrics(space, params, goal, fidelity="fast"):
        return PluginEvaluation(
            metrics={"synthetic": float(params["root_chord"])}, warnings=[]
        )


def test_register_scorer_validates_and_serves_a_structural_plugin() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        register_scorer("", _TinyPlugin())
    with pytest.raises(TypeError, match="metric_catalog"):
        register_scorer("unit_missing_catalog", _NoMethods())
    with pytest.raises(TypeError, match="evaluate_metrics"):
        register_scorer("unit_missing_evaluate", _CatalogOnly())

    scorer_id = "unit_tiny_scorer"
    register_scorer(scorer_id, _TinyPlugin())
    tiny_space = SPACE.model_copy(update={"id": "unit_tiny_space", "scorer": scorer_id})
    tiny_goal = Goal(
        source_text="maximize synthetic",
        objectives=[Objective(metric="synthetic", direction="maximize")],
        parsed_by="manual",
    )
    score = evaluate(tiny_space, {"root_chord": 91.26}, tiny_goal)
    assert score.metrics == {"synthetic": 91.5}
    assert score.objective_scores["synthetic"] == pytest.approx(
        (91.5 - 50.0) / (130.0 - 50.0)
    )
    with pytest.raises(ValueError, match="does not support high fidelity"):
        validate_high_fidelity(tiny_space, {}, tiny_goal)


def test_high_fidelity_returns_complete_score_or_explicit_fallback() -> None:
    params = canonicalize(SPACE, {})
    fast = evaluate(SPACE, params, GOAL)
    high = validate_high_fidelity(SPACE, params, GOAL)

    assert high.fidelity == "high"
    assert list(high.metrics) == CATALOG_NAMES
    assert set(high.objective_scores) == {
        objective.metric for objective in GOAL.objectives
    }
    assert all(math.isfinite(value) for value in high.metrics.values())
    assert math.isfinite(high.aggregate) and high.aggregate <= 1.0
    assert high.metrics["drag_n"] > 0.0
    assert isinstance(high.warnings, list)

    # The current high-fidelity path changes only the aerodynamic method.
    unchanged = {
        "stability_margin_cal",
        "cp_mm",
        "cg_mm",
        "fin_mass_g",
        "fin_mass_total_g",
        "flutter_velocity_mps",
        "flutter_margin",
        "cn_alpha_fins",
        "aft_overhang_mm",
        "planform_area_cm2",
    }
    for metric in unchanged:
        assert high.metrics[metric] == fast.metrics[metric]

    # Missing/failed AeroSandbox is valid only when disclosed to the caller.
    fallback_warnings = [warning for warning in high.warnings if "fallback" in warning.lower()]
    if fallback_warnings:
        assert any("AeroSandbox" in warning for warning in fallback_warnings)

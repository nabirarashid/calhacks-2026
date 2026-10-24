"""Focused tests for the frozen B.6 aggregation and Pareto behavior."""

import json
from pathlib import Path
from typing import Dict

import pytest

from shared.contracts import (
    Constraint,
    DesignResult,
    DesignSpace,
    Goal,
    MetricInfo,
    Score,
)
from sim.aggregate import aggregate, objective_score
from sim.pareto import pareto_front, pareto_ranks


FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"


def _load(name: str) -> object:
    with (FIXTURES / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _model(model: object, data: object) -> object:
    # The project pins Pydantic v2, but this keeps the focused test usable in
    # minimal developer environments that still have Pydantic v1.
    validator = getattr(model, "model_validate", None)
    return validator(data) if validator is not None else model.parse_obj(data)  # type: ignore[attr-defined]


@pytest.fixture
def space() -> DesignSpace:
    return _model(DesignSpace, _load("design_space_fin.json"))  # type: ignore[return-value]


@pytest.fixture
def goal() -> Goal:
    return _model(Goal, _load("goal_example.json"))  # type: ignore[return-value]


@pytest.fixture
def catalog() -> list:
    return [_model(MetricInfo, item) for item in _load("metric_catalog_fin.json")]  # type: ignore[union-attr]


@pytest.fixture
def fixture_design() -> DesignResult:
    return _model(DesignResult, _load("design_result_example.json"))  # type: ignore[return-value]


def test_objective_scoring_follows_b6_and_clips(catalog: list) -> None:
    info = {item.name: item for item in catalog}
    assert objective_score(2.0, "target", info["stability_margin_cal"], 2.5, 1.0) == pytest.approx(0.5)
    assert objective_score(2.1, "minimize", info["drag_n"]) == pytest.approx(0.5)
    assert objective_score(2.75, "maximize", info["flutter_margin"]) == pytest.approx(0.5)
    assert objective_score(-100.0, "minimize", info["drag_n"]) == 1.0
    assert objective_score(100.0, "minimize", info["drag_n"]) == 0.0


def test_fixture_inputs_produce_weighted_feasible_aggregate(
    space: DesignSpace, goal: Goal, catalog: list, fixture_design: DesignResult
) -> None:
    scores, violations, feasible, total = aggregate(
        space, fixture_design.params, fixture_design.score.metrics, goal, catalog
    )
    expected = sum(
        objective.weight * scores[objective.metric] for objective in goal.objectives
    ) / sum(objective.weight for objective in goal.objectives)
    assert violations == []
    assert feasible
    assert total == pytest.approx(expected)
    assert all(0.0 <= value <= 1.0 for value in scores.values())


def test_metric_and_param_constraints_use_catalog_or_param_ranges(
    space: DesignSpace, goal: Goal, catalog: list, fixture_design: DesignResult
) -> None:
    changed_metrics = dict(fixture_design.score.metrics)
    changed_metrics["fin_mass_total_g"] = 230.0
    changed_metrics["aft_overhang_mm"] = 40.0
    constraints = list(goal.constraints) + [
        Constraint(ref="param:root_chord", op="<=", value=80.0, hard=False)
    ]
    constrained_goal = goal.model_copy(update={"constraints": constraints})

    _, violations, feasible, total = aggregate(
        space, fixture_design.params, changed_metrics, constrained_goal, catalog
    )
    by_ref = {violation.ref: violation for violation in violations}
    assert by_ref["fin_mass_total_g"].amount == pytest.approx((230.0 - 40.0) / 190.0)
    assert by_ref["aft_overhang_mm"].amount == pytest.approx(40.0 / 80.0)
    assert by_ref["param:root_chord"].amount == pytest.approx((92.0 - 80.0) / 80.0)
    assert not feasible
    assert total < 0.0


def test_fixed_numeric_and_choice_params_are_hard_violations(
    space: DesignSpace, goal: Goal, catalog: list, fixture_design: DesignResult
) -> None:
    fixed = {"thickness": 3.0, "edge_profile": "rounded"}
    fixed_goal = goal.model_copy(update={"constraints": [], "fixed_params": fixed})
    _, violations, feasible, total = aggregate(
        space, fixture_design.params, fixture_design.score.metrics, fixed_goal, catalog
    )
    by_ref = {violation.ref: violation for violation in violations}
    assert by_ref["param:thickness"].amount == pytest.approx(0.6 / 3.0)
    assert by_ref["param:edge_profile"].amount == 1.0
    assert by_ref["param:edge_profile"].limit == 0.0
    assert by_ref["param:edge_profile"].actual == 1.0
    assert not feasible
    assert total == pytest.approx(-1.2)


def test_soft_penalty_follows_frozen_formula_without_hidden_clipping(
    space: DesignSpace, goal: Goal, catalog: list, fixture_design: DesignResult
) -> None:
    soft = [
        Constraint(ref="aft_overhang_mm", op="<=", value=-80.0, hard=False)
        for _ in range(20)
    ]
    feasible_goal = goal.model_copy(update={"objectives": [], "constraints": soft})
    _, _, is_feasible, feasible_total = aggregate(
        space, fixture_design.params, fixture_design.score.metrics, feasible_goal, catalog
    )
    hard_goal = goal.model_copy(
        update={
            "objectives": [],
            "constraints": [
                Constraint(ref="fin_mass_total_g", op="<=", value=32.0, hard=True)
            ],
        }
    )
    _, _, is_hard_feasible, infeasible_total = aggregate(
        space, fixture_design.params, fixture_design.score.metrics, hard_goal, catalog
    )
    assert is_feasible and not is_hard_feasible
    expected_soft = -0.1 * sum(v.amount for v in aggregate(
        space, fixture_design.params, fixture_design.score.metrics, feasible_goal, catalog
    )[1])
    assert feasible_total == pytest.approx(expected_soft)
    assert infeasible_total < 0.0


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"objectives": []}, ""),
        ({"fixed_params": {"edge_profile": "winglet"}}, "invalid choice"),
        ({"fixed_params": {"does_not_exist": 1.0}}, "unknown parameter"),
    ],
)
def test_goal_validation_errors_are_actionable(
    update: Dict[str, object],
    message: str,
    space: DesignSpace,
    goal: Goal,
    catalog: list,
    fixture_design: DesignResult,
) -> None:
    changed = goal.model_copy(update=update)
    if not message:
        # Constraint-only goals are valid and receive an objective base of 0.
        _, _, feasible, total = aggregate(
            space, fixture_design.params, fixture_design.score.metrics, changed, catalog
        )
        assert feasible and total == 0.0
        return
    with pytest.raises(ValueError, match=message):
        aggregate(space, fixture_design.params, fixture_design.score.metrics, changed, catalog)


def _score(goal: Goal, values: list, feasible: bool = True) -> Score:
    return Score(
        metrics={},
        objective_scores={
            objective.metric: value for objective, value in zip(goal.objectives, values)
        },
        feasible=feasible,
        aggregate=0.0 if feasible else -1.0,
    )


def test_pareto_sorting_uses_normalized_scores_and_feasibility(goal: Goal) -> None:
    scores = [
        _score(goal, [0.8, 0.8, 0.8]),
        _score(goal, [0.9, 0.7, 0.8]),
        _score(goal, [0.7, 0.7, 0.7]),
        _score(goal, [1.0, 1.0, 1.0], feasible=False),
        _score(goal, [0.5, 0.5, 0.5], feasible=False),
    ]
    assert pareto_ranks(scores, goal) == [0, 0, 1, 2, 3]
    assert pareto_front(scores, goal) == [0, 1]


def test_all_infeasible_still_have_a_front(goal: Goal) -> None:
    scores = [
        _score(goal, [0.8, 0.8, 0.8], feasible=False),
        _score(goal, [0.7, 0.7, 0.7], feasible=False),
    ]
    assert pareto_ranks(scores, goal) == [0, 1]
    assert pareto_front(scores, goal) == [0]


def test_pareto_rejects_missing_objective_score(goal: Goal) -> None:
    score = _score(goal, [0.8, 0.8, 0.8])
    del score.objective_scores[goal.objectives[0].metric]
    with pytest.raises(ValueError, match="missing objective score"):
        pareto_ranks([score], goal)

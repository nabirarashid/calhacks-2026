import json
from collections import Counter
from pathlib import Path

import pytest

from shared.contracts import DesignSpace, Goal, Score, canonicalize
from sim.landscape import landscape, latin_hypercube_params
from sim.sensitivity import sensitivity


FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "fixtures"
SPACE = DesignSpace.model_validate(json.loads((FIXTURES / "design_space_fin.json").read_text()))
GOAL = Goal.model_validate(json.loads((FIXTURES / "goal_example.json").read_text()))


def _score(params):
    edge_effect = {"square": -2.0, "rounded": 1.0, "beveled": 5.0}[params["edge_profile"]]
    metric = (
        2.0 * float(params["root_chord"])
        + 10.0 * float(params["fin_count"])
        + edge_effect
    )
    return Score(
        metrics={"synthetic": metric},
        objective_scores={},
        violations=[],
        feasible=True,
        aggregate=0.5,
    )


def _evaluate(_space, params, _goal):
    return _score(params)


def test_sensitivity_normalizes_continuous_and_checks_all_discrete_alternatives():
    params = canonicalize(SPACE, {})
    calls = []

    def tracking_evaluate(space, candidate, goal):
        calls.append(dict(candidate))
        return _evaluate(space, candidate, goal)

    result = sensitivity(SPACE, params, GOAL, evaluate_fn=tracking_evaluate)

    # d(2*root_chord)/d(root_chord) * its 80 mm range.
    assert result["root_chord"]["synthetic"] == pytest.approx(160.0)
    # Baseline count is four, so the only alternative moves the metric by -10.
    assert result["fin_count"]["synthetic"] == pytest.approx(-10.0)
    # All two non-baseline profiles were evaluated; beveled has the largest
    # magnitude change from rounded: 5 - 1 = +4.
    assert result["edge_profile"]["synthetic"] == pytest.approx(4.0)
    tested_profiles = {
        call["edge_profile"] for call in calls if call["edge_profile"] != params["edge_profile"]
    }
    assert tested_profiles == {"square", "beveled"}


def test_latin_hypercube_is_deterministic_canonical_and_balances_discrete_values():
    first = latin_hypercube_params(SPACE, n=12, seed=41)
    second = latin_hypercube_params(SPACE, n=12, seed=41)

    assert first == second
    assert len(first) == 12
    assert all(candidate == canonicalize(SPACE, candidate) for candidate in first)
    assert Counter(p["edge_profile"] for p in first) == {
        "square": 4,
        "rounded": 4,
        "beveled": 4,
    }
    assert Counter(p["fin_count"] for p in first) == {3: 6, 4: 6}

    # Each root-chord sample occupies a different Latin-hypercube stratum.
    occupied = {
        min(11, int((float(p["root_chord"]) - 50.0) / (130.0 - 50.0) * 12))
        for p in first
    }
    assert occupied == set(range(12))


def test_landscape_has_exact_size_uses_batch_and_reads_cache(tmp_path):
    batch_calls = []

    def batch_evaluate(space, params_list, goal, workers=0):
        batch_calls.append((len(params_list), workers))
        return [_evaluate(space, params, goal) for params in params_list]

    first = landscape(
        SPACE,
        GOAL,
        n=17,
        seed=9,
        batch_evaluate_fn=batch_evaluate,
        workers=3,
        cache_dir=tmp_path,
    )
    assert len(first) == 17
    assert batch_calls == [(17, 3)]

    # A cache hit does not require an evaluator and round-trips typed scores.
    second = landscape(SPACE, GOAL, n=17, seed=9, cache_dir=tmp_path)
    assert second == first
    assert batch_calls == [(17, 3)]


def test_corrupt_and_unwritable_cache_failures_are_nonfatal(tmp_path, monkeypatch):
    good = landscape(SPACE, GOAL, n=3, seed=2, evaluate_fn=_evaluate, cache_dir=tmp_path)
    cache_file = next(tmp_path.glob("*.json"))
    cache_file.write_text("not json")
    regenerated = landscape(SPACE, GOAL, n=3, seed=2, evaluate_fn=_evaluate, cache_dir=tmp_path)
    assert regenerated == good

    def denied(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(Path, "write_text", denied)
    uncached = landscape(
        SPACE,
        GOAL,
        n=4,
        seed=3,
        evaluate_fn=_evaluate,
        cache_dir=tmp_path / "unwritable",
    )
    assert len(uncached) == 4


def test_landscape_zero_and_invalid_sizes(tmp_path):
    assert landscape(SPACE, GOAL, n=0, seed=0, evaluate_fn=_evaluate, cache_dir=tmp_path) == []
    with pytest.raises(ValueError, match="non-negative"):
        landscape(SPACE, GOAL, n=-1, evaluate_fn=_evaluate, cache_dir=tmp_path)


def test_landscape_cache_key_includes_goal(tmp_path):
    alternate_goal = GOAL.model_copy(deep=True)
    alternate_goal.source_text = "different"
    landscape(SPACE, GOAL, n=2, seed=4, evaluate_fn=_evaluate, cache_dir=tmp_path)
    landscape(SPACE, alternate_goal, n=2, seed=4, evaluate_fn=_evaluate, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 2

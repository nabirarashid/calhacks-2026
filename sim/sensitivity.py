"""Local sensitivity analysis for simulation scores.

The evaluator is injected by :mod:`sim.api`.  Keeping that dependency pointed
inward avoids importing the public API here (and therefore avoids a circular
import when the API re-exports :func:`sensitivity`).
"""

import math
from typing import Callable, Dict, Iterable, List

from shared.contracts import DesignSpace, Goal, ParamSpec, ParamValue, Score, canonicalize


EvaluateFn = Callable[[DesignSpace, Dict[str, ParamValue], Goal], Score]


def _integer_alternatives(spec: ParamSpec) -> List[int]:
    """Return every canonical integer value allowed by *spec*, in order."""
    if spec.min is None or spec.max is None:
        return []
    lower = int(math.ceil(spec.min))
    upper = int(math.floor(spec.max))
    return list(range(lower, upper + 1))


def _discrete_alternatives(spec: ParamSpec) -> Iterable[ParamValue]:
    if spec.kind == "choice":
        return list(spec.choices or [])
    if spec.kind == "integer":
        return _integer_alternatives(spec)
    return []


def _largest_signed_delta(deltas: List[float]) -> float:
    """Choose the largest effect while preserving the winning direction.

    Ties retain the first alternative in the frozen design-space order, which
    makes categorical sensitivities deterministic.
    """
    if not deltas:
        return 0.0
    return max(deltas, key=abs)


def sensitivity(
    space: DesignSpace,
    params: Dict[str, ParamValue],
    goal: Goal,
    *,
    evaluate_fn: EvaluateFn,
) -> Dict[str, Dict[str, float]]:
    """Estimate the metric effect of each design parameter.

    Continuous values use a central finite difference at plus/minus 5% of the
    full parameter range.  At a boundary the interval is clipped, and the
    observed slope is still scaled to the *full* range::

        (metric(high) - metric(low)) / (high - low) * (max - min)

    Integer and choice parameters evaluate every alternative to the current
    value.  Since the public contract only permits one float per metric, those
    deltas are summarized as the signed, largest-magnitude alternative effect.
    This is useful to a critic ("the most this choice can move the metric") and
    remains deterministic even when two alternatives tie.

    Only ``Score.metrics`` are reported; aggregate is goal-specific and is not
    a physical metric.  Inputs and every perturbed design are canonicalized.
    """
    baseline_params = canonicalize(space, params)
    result = {}  # type: Dict[str, Dict[str, float]]
    baseline_score = None  # type: Score

    for spec in space.parameters:
        if spec.kind == "continuous":
            if spec.min is None or spec.max is None:
                continue
            span = float(spec.max - spec.min)
            if span <= 0.0:
                continue

            half_interval = 0.05 * span
            center = float(baseline_params[spec.name])
            low_params = dict(baseline_params)
            high_params = dict(baseline_params)
            low_params[spec.name] = max(float(spec.min), center - half_interval)
            high_params[spec.name] = min(float(spec.max), center + half_interval)
            low_params = canonicalize(space, low_params)
            high_params = canonicalize(space, high_params)

            low_value = float(low_params[spec.name])
            high_value = float(high_params[spec.name])
            observed_interval = high_value - low_value
            if observed_interval <= 0.0:
                continue

            low_score = evaluate_fn(space, low_params, goal)
            high_score = evaluate_fn(space, high_params, goal)
            metric_names = sorted(set(low_score.metrics) & set(high_score.metrics))
            result[spec.name] = {
                metric: (float(high_score.metrics[metric]) - float(low_score.metrics[metric]))
                / observed_interval
                * span
                for metric in metric_names
            }
            continue

        alternatives = [
            value
            for value in _discrete_alternatives(spec)
            if value != baseline_params[spec.name]
        ]
        if not alternatives:
            continue
        if baseline_score is None:
            baseline_score = evaluate_fn(space, baseline_params, goal)

        deltas = {}  # type: Dict[str, List[float]]
        for alternative in alternatives:
            alternative_params = dict(baseline_params)
            alternative_params[spec.name] = alternative
            alternative_params = canonicalize(space, alternative_params)
            alternative_score = evaluate_fn(space, alternative_params, goal)
            for metric in sorted(set(baseline_score.metrics) & set(alternative_score.metrics)):
                deltas.setdefault(metric, []).append(
                    float(alternative_score.metrics[metric])
                    - float(baseline_score.metrics[metric])
                )
        result[spec.name] = {
            metric: _largest_signed_delta(metric_deltas)
            for metric, metric_deltas in sorted(deltas.items())
        }

    return result

"""Objective scoring and constraint aggregation for simulation results.

This module implements the aggregation rule frozen in :mod:`PLAN.md` B.6.  It
does not calculate physics; callers provide the canonical design parameters,
raw metrics, goal, and the scorer's metric catalog.
"""

import math
from numbers import Real
from typing import Dict, List, Mapping, Optional, Tuple

from shared.contracts import (
    Constraint,
    DesignSpace,
    Goal,
    MetricInfo,
    ParamSpec,
    ParamValue,
    Violation,
)


_COMPARISON_EPSILON = 1e-9


def _finite_number(value: object, description: str) -> float:
    """Return *value* as a finite float or raise an actionable error."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("%s must be a number; got %r" % (description, value))
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("%s must be finite; got %r" % (description, value))
    return result


def _normalization_span(info: MetricInfo) -> float:
    lo = _finite_number(info.typical_min, "metric %r typical_min" % info.name)
    hi = _finite_number(info.typical_max, "metric %r typical_max" % info.name)
    span = hi - lo
    if span <= 0.0:
        raise ValueError(
            "metric %r must have typical_max greater than typical_min; got %s <= %s"
            % (info.name, hi, lo)
        )
    return span


def _catalog_by_name(catalog: List[MetricInfo]) -> Dict[str, MetricInfo]:
    result = {}  # type: Dict[str, MetricInfo]
    for info in catalog:
        if info.name in result:
            raise ValueError("metric catalog contains duplicate metric %r" % info.name)
        _normalization_span(info)
        result[info.name] = info
    return result


def objective_score(
    x: float,
    direction: str,
    info: MetricInfo,
    target: Optional[float] = None,
    tolerance: Optional[float] = None,
) -> float:
    """Convert one raw metric to a ``[0, 1]`` higher-is-better score.

    ``minimize`` and ``maximize`` use the metric's catalog normalization
    range.  ``target`` uses the explicit target/tolerance when supplied, then
    the catalog defaults, and finally the midpoint and quarter-range fallbacks
    specified by the frozen mock.
    """
    actual = _finite_number(x, "metric %r value" % info.name)
    span = _normalization_span(info)
    lo = float(info.typical_min)
    fraction = min(1.0, max(0.0, (actual - lo) / span))

    if direction == "maximize":
        return fraction
    if direction == "minimize":
        return 1.0 - fraction
    if direction != "target":
        raise ValueError(
            "objective %r has unsupported direction %r; expected minimize, maximize, or target"
            % (info.name, direction)
        )

    if target is not None:
        resolved_target = _finite_number(target, "objective %r target" % info.name)
    elif info.default_target is not None:
        resolved_target = _finite_number(
            info.default_target, "metric %r default_target" % info.name
        )
    else:
        resolved_target = lo + span / 2.0

    if tolerance is not None:
        resolved_tolerance = _finite_number(
            tolerance, "objective %r tolerance" % info.name
        )
    elif info.default_tolerance is not None:
        resolved_tolerance = _finite_number(
            info.default_tolerance, "metric %r default_tolerance" % info.name
        )
    else:
        resolved_tolerance = span / 4.0
    if resolved_tolerance <= 0.0:
        raise ValueError(
            "objective %r tolerance must be greater than zero; got %s"
            % (info.name, resolved_tolerance)
        )

    return max(0.0, 1.0 - abs(actual - resolved_target) / resolved_tolerance)


def _param_by_name(space: DesignSpace, name: str) -> ParamSpec:
    try:
        return space.param(name)
    except KeyError:
        known = ", ".join(sorted(p.name for p in space.parameters)) or "<none>"
        raise ValueError(
            "unknown parameter %r in goal; design space %r parameters are: %s"
            % (name, space.id, known)
        )


def _parameter_value(
    params: Mapping[str, ParamValue], spec: ParamSpec, description: str
) -> ParamValue:
    if spec.name not in params:
        raise ValueError("%s references missing parameter %r" % (description, spec.name))
    value = params[spec.name]
    if spec.kind == "choice":
        if not isinstance(value, str):
            raise ValueError(
                "parameter %r is a choice and must be a string; got %r"
                % (spec.name, value)
            )
        if spec.choices is not None and value not in spec.choices:
            raise ValueError(
                "parameter %r has invalid choice %r; expected one of %s"
                % (spec.name, value, ", ".join(repr(v) for v in spec.choices))
            )
        return value
    return _finite_number(value, "parameter %r value" % spec.name)


def _parameter_span(spec: ParamSpec) -> float:
    if spec.min is None or spec.max is None:
        raise ValueError(
            "numeric parameter %r needs min and max to normalize constraint violations"
            % spec.name
        )
    lo = _finite_number(spec.min, "parameter %r min" % spec.name)
    hi = _finite_number(spec.max, "parameter %r max" % spec.name)
    if hi <= lo:
        raise ValueError(
            "numeric parameter %r must have max greater than min; got %s <= %s"
            % (spec.name, hi, lo)
        )
    return hi - lo


def _is_satisfied(actual: float, op: str, limit: float, span: float) -> bool:
    if op == "<=":
        return actual <= limit + _COMPARISON_EPSILON
    if op == ">=":
        return actual >= limit - _COMPARISON_EPSILON
    if op == "==":
        return abs(actual - limit) <= max(1e-6, 1e-3 * span)
    raise ValueError("unsupported constraint operator %r; expected <=, >=, or ==" % op)


def _numeric_violation(
    ref: str,
    op: str,
    limit: object,
    actual: object,
    span: float,
    hard: bool,
) -> Optional[Violation]:
    numeric_limit = _finite_number(limit, "constraint %r limit" % ref)
    numeric_actual = _finite_number(actual, "constraint %r actual value" % ref)
    if _is_satisfied(numeric_actual, op, numeric_limit, span):
        return None
    return Violation(
        ref=ref,
        op=op,
        limit=numeric_limit,
        actual=numeric_actual,
        amount=abs(numeric_actual - numeric_limit) / span,
        hard=hard,
    )


def _constraint_violation(
    constraint: Constraint,
    space: DesignSpace,
    params: Mapping[str, ParamValue],
    metrics: Mapping[str, float],
    info_by_name: Mapping[str, MetricInfo],
) -> Optional[Violation]:
    ref = constraint.ref
    if ref.startswith("param:"):
        name = ref[len("param:") :]
        if not name:
            raise ValueError("constraint ref 'param:' is missing a parameter name")
        spec = _param_by_name(space, name)
        actual = _parameter_value(params, spec, "constraint %r" % ref)
        if spec.kind == "choice":
            raise ValueError(
                "constraint %r cannot compare a choice parameter to numeric value %r; "
                "pin choice values through goal.fixed_params instead"
                % (ref, constraint.value)
            )
        return _numeric_violation(
            ref,
            constraint.op,
            constraint.value,
            actual,
            _parameter_span(spec),
            constraint.hard,
        )

    if ref not in info_by_name:
        raise ValueError("constraint references unknown metric %r" % ref)
    if ref not in metrics:
        raise ValueError("constraint references missing metric value %r" % ref)
    return _numeric_violation(
        ref,
        constraint.op,
        constraint.value,
        metrics[ref],
        _normalization_span(info_by_name[ref]),
        constraint.hard,
    )


def _fixed_param_violation(
    name: str,
    expected: ParamValue,
    space: DesignSpace,
    params: Mapping[str, ParamValue],
) -> Optional[Violation]:
    spec = _param_by_name(space, name)
    actual = _parameter_value(params, spec, "fixed parameter %r" % name)
    ref = "param:" + name

    if spec.kind == "choice":
        if not isinstance(expected, str):
            raise ValueError(
                "fixed choice parameter %r must be a string; got %r" % (name, expected)
            )
        if spec.choices is not None and expected not in spec.choices:
            raise ValueError(
                "fixed parameter %r has invalid choice %r; expected one of %s"
                % (name, expected, ", ".join(repr(v) for v in spec.choices))
            )
        if actual == expected:
            return None
        # Violation fields are numeric in the frozen contract.  A choice
        # mismatch is therefore represented as 0 -> 1 and is a full-range
        # hard violation, matching the CP0 mock behavior.
        return Violation(
            ref=ref, op="==", limit=0.0, actual=1.0, amount=1.0, hard=True
        )

    span = _parameter_span(spec)
    return _numeric_violation(ref, "==", expected, actual, span, True)


def aggregate(
    space: DesignSpace,
    params: Dict[str, ParamValue],
    metrics: Dict[str, float],
    goal: Goal,
    catalog: List[MetricInfo],
) -> Tuple[Dict[str, float], List[Violation], bool, float]:
    """Score objectives, enforce constraints, and calculate aggregate fitness.

    The return tuple is ``(objective_scores, violations, feasible, aggregate)``
    and intentionally matches the frozen fake simulator.  Parameters should be
    canonicalized by ``sim.api.evaluate`` before calling this function.
    """
    if not isinstance(params, Mapping):
        raise ValueError("params must be a mapping of parameter names to values")
    if not isinstance(metrics, Mapping):
        raise ValueError("metrics must be a mapping of metric names to numbers")

    info_by_name = _catalog_by_name(catalog)
    objective_scores = {}  # type: Dict[str, float]
    numerator = 0.0
    denominator = 0.0
    for objective in goal.objectives:
        metric = objective.metric
        if metric in objective_scores:
            raise ValueError(
                "goal contains duplicate objective metric %r; objective_scores are keyed by metric"
                % metric
            )
        if metric not in info_by_name:
            raise ValueError("objective references unknown metric %r" % metric)
        if metric not in metrics:
            raise ValueError("objective references missing metric value %r" % metric)
        weight = _finite_number(objective.weight, "objective %r weight" % metric)
        if weight < 0.0:
            raise ValueError("objective %r weight must be non-negative; got %s" % (metric, weight))
        score = objective_score(
            metrics[metric],
            objective.direction,
            info_by_name[metric],
            objective.target,
            objective.tolerance,
        )
        objective_scores[metric] = score
        numerator += weight * score
        denominator += weight

    violations = []  # type: List[Violation]
    for constraint in goal.constraints:
        violation = _constraint_violation(
            constraint, space, params, metrics, info_by_name
        )
        if violation is not None:
            violations.append(violation)
    for name, expected in goal.fixed_params.items():
        violation = _fixed_param_violation(name, expected, space, params)
        if violation is not None:
            violations.append(violation)

    hard_sum = sum(v.amount for v in violations if v.hard)
    soft_sum = sum(v.amount for v in violations if not v.hard)
    feasible = not any(v.hard for v in violations)
    if feasible:
        weighted_score = numerator / denominator if denominator > 0.0 else 0.0
        aggregate_score = weighted_score - 0.1 * soft_sum
    else:
        aggregate_score = -hard_sum - 0.1 * soft_sum

    return objective_scores, violations, feasible, aggregate_score

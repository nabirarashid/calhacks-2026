"""Public, deterministic simulation API consumed by ``backend.wiring``.

This module is the only cross-section import surface for S2.  It owns scorer
registration, contract validation, aggregation, batching, and the analysis
helpers.  Physics implementations remain isolated in ``sim.plugins``.
"""
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, List, Tuple

from shared.contracts import (
    DesignSpace,
    Goal,
    MetricInfo,
    ParamValue,
    Score,
    canonicalize,
)

from sim.aggregate import aggregate
from sim.pareto import pareto_front as _pareto_front
from sim.pareto import pareto_ranks as _pareto_ranks


_SCORERS = {}  # type: Dict[str, object]


def _default_plugin(scorer_id: str) -> object:
    if scorer_id == "fin_v1":
        from sim.plugins.fin_v1 import PLUGIN

        return PLUGIN
    raise KeyError("unknown scorer: %s" % scorer_id)


def _plugin(scorer_id: str) -> object:
    if scorer_id not in _SCORERS:
        _SCORERS[scorer_id] = _default_plugin(scorer_id)
    return _SCORERS[scorer_id]


def register_scorer(scorer_id: str, plugin: object) -> None:
    """Register a scorer plugin for a discovered Tier-3 design space."""
    if not scorer_id:
        raise ValueError("scorer_id must not be empty")
    for method in ("metric_catalog", "evaluate_metrics"):
        if not callable(getattr(plugin, method, None)):
            raise TypeError("scorer plugin must define %s()" % method)
    _SCORERS[scorer_id] = plugin


def metric_catalog(scorer: str) -> List[MetricInfo]:
    """Return a defensive copy of the scorer's published metrics."""
    catalog = getattr(_plugin(scorer), "metric_catalog")()
    return [m.model_copy(deep=True) for m in catalog]


def _evaluate_metrics(plugin: object, space: DesignSpace, params: Dict[str, ParamValue],
                      goal: Goal, fidelity: str):
    if fidelity == "high":
        hifi = getattr(plugin, "hifi", None)
        if not callable(hifi):
            raise ValueError("scorer %s does not support high fidelity" % space.scorer)
        return hifi(space, params, goal)
    return getattr(plugin, "evaluate_metrics")(space, params, goal, fidelity="fast")


def evaluate(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal,
             fidelity: str = "fast") -> Score:
    """Canonicalize one design, evaluate physics, and apply the frozen goal rule."""
    if fidelity not in ("fast", "high"):
        raise ValueError("fidelity must be 'fast' or 'high'")
    started = time.perf_counter()
    canonical = canonicalize(space, params)
    plugin = _plugin(space.scorer)
    result = _evaluate_metrics(plugin, space, canonical, goal, fidelity)
    metrics = {str(k): float(v) for k, v in result.metrics.items()}
    catalog = metric_catalog(space.scorer)
    expected = {m.name for m in catalog}
    actual = set(metrics)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError("scorer metric mismatch; missing=%s extra=%s" % (missing, extra))
    objective_scores, violations, feasible, aggregate_score = aggregate(
        space, canonical, metrics, goal, catalog,
    )
    return Score(
        metrics=metrics,
        objective_scores=objective_scores,
        violations=violations,
        feasible=feasible,
        aggregate=float(aggregate_score),
        warnings=list(result.warnings),
        fidelity=fidelity,
        eval_ms=(time.perf_counter() - started) * 1000.0,
    )


def _evaluate_job(args: Tuple[DesignSpace, Dict[str, ParamValue], Goal]) -> Score:
    """Spawn-safe module-level process-pool entry point."""
    space, params, goal = args
    return evaluate(space, params, goal)


def evaluate_batch(space: DesignSpace, params_list: List[Dict[str, ParamValue]], goal: Goal,
                   workers: int = 0) -> List[Score]:
    """Evaluate designs in input order, optionally using spawn-safe workers."""
    if workers < 0:
        raise ValueError("workers must be >= 0")
    if not params_list:
        return []
    if workers == 0 or len(params_list) == 1:
        return [evaluate(space, params, goal) for params in params_list]
    # Dynamically registered plugins may not exist in spawned interpreters.  The
    # frozen fin_v1 plugin is importable and is the only parallel scorer today.
    if space.scorer != "fin_v1":
        return [evaluate(space, params, goal) for params in params_list]
    context = multiprocessing.get_context("spawn")
    jobs = [(space, params, goal) for params in params_list]
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as pool:
        return list(pool.map(_evaluate_job, jobs))


def pareto_ranks(scores: List[Score], goal: Goal) -> List[int]:
    return _pareto_ranks(scores, goal)


def pareto_front(scores: List[Score], goal: Goal) -> List[int]:
    return _pareto_front(scores, goal)


def sensitivity(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal) -> Dict[str, Dict[str, float]]:
    from sim.sensitivity import sensitivity as calculate_sensitivity

    return calculate_sensitivity(space, params, goal, evaluate_fn=evaluate)


def landscape(space: DesignSpace, goal: Goal, n: int = 2000, seed: int = 0) \
        -> List[Tuple[Dict[str, ParamValue], Score]]:
    from sim.landscape import landscape as calculate_landscape

    return calculate_landscape(
        space,
        goal,
        n=n,
        seed=seed,
        batch_evaluate_fn=evaluate_batch,
        workers=4 if n >= 128 else 0,
    )


def validate_high_fidelity(space: DesignSpace, params: Dict[str, ParamValue], goal: Goal) -> Score:
    return evaluate(space, params, goal, fidelity="high")

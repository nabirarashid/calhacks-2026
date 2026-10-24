"""Classic baselines on the SAME evaluation budget, goal and evaluate() as the agent.

CMA-ES (pycma) over params normalized to [0,1] (integers/choices encoded as
continuous [0,1) bins), starting at the default design with sigma0 0.25 and
popsize N; random search uniform over the space. Eval #1 is the default design
for both, as for the agent.
"""
import random
import warnings
from typing import Callable, Dict, List

from shared.contracts import DesignResult, DesignSpace, Goal, ParamValue, canonicalize, make_design_id, param_hash

from backend.agents.fallback import random_params


def _encode(space: DesignSpace, params: Dict[str, ParamValue]) -> List[float]:
    x = []
    for p in space.parameters:
        if p.kind == "choice":
            x.append(((p.choices or []).index(params[p.name]) + 0.5) / len(p.choices or [1]))
        else:
            x.append((float(params[p.name]) - float(p.min)) / (float(p.max) - float(p.min)))  # type: ignore[arg-type]
    return x


def _decode(space: DesignSpace, x: List[float]) -> Dict[str, ParamValue]:
    out = {}  # type: Dict[str, ParamValue]
    for p, v in zip(space.parameters, x):
        v = min(1.0, max(0.0, float(v)))
        if p.kind == "choice":
            ch = p.choices or [str(p.default)]
            out[p.name] = ch[min(len(ch) - 1, int(v * len(ch)))]
        elif p.kind == "integer":
            lo, hi = int(p.min), int(p.max)  # type: ignore[arg-type]
            out[p.name] = min(hi, lo + int(v * (hi - lo + 1)))
        else:
            out[p.name] = float(p.min) + v * (float(p.max) - float(p.min))  # type: ignore[arg-type]
    return out


def _result(space: DesignSpace, run_id: str, origin: str, i: int, params: Dict[str, ParamValue], score,
            population: int) -> DesignResult:
    return DesignResult(design_id=make_design_id(run_id, i // population, origin, i % population), run_id=run_id,
                        generation=i // population, origin=origin, params=params,  # type: ignore[arg-type]
                        param_hash=param_hash(space, params), operator="seed" if i == 0 else "novel", score=score)


def run_random(space: DesignSpace, goal: Goal, evaluate: Callable, budget: int, seed: int, run_id: str,
               population: int, default: Dict[str, ParamValue]) -> List[DesignResult]:
    rng = random.Random(seed * 7919 + 1)
    out = []
    for i in range(budget):
        p = default if i == 0 else canonicalize(space, dict(random_params(space, rng), **goal.fixed_params))
        out.append(_result(space, run_id, "baseline_random", i, p, evaluate(space, p, goal), population))
    return out


def run_cmaes(space: DesignSpace, goal: Goal, evaluate: Callable, budget: int, seed: int, run_id: str,
              population: int, default: Dict[str, ParamValue]) -> List[DesignResult]:
    import cma
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        es = cma.CMAEvolutionStrategy(_encode(space, default), 0.25,
                                      {"popsize": population, "seed": seed + 1, "verbose": -9, "bounds": [0, 1]})
    out = []  # type: List[DesignResult]
    while len(out) < budget:
        xs = es.ask()
        fits = []
        for x in xs:
            i = len(out)
            p = default if i == 0 else canonicalize(space, dict(_decode(space, list(x)), **goal.fixed_params))
            d = _result(space, run_id, "baseline_cmaes", i, p, evaluate(space, p, goal), population)
            out.append(d)
            fits.append(-d.score.aggregate)
            if len(out) >= budget:
                break
        if len(fits) == len(xs):
            es.tell(xs, fits)
    return out


RUNNERS = {"cmaes": run_cmaes, "random": run_random}


def editable_view(space: DesignSpace, goal: Goal, start: Dict[str, ParamValue], evaluate: Callable):
    """Restrict a baseline to the params the user allowed to change (PLAN.md B.4: baselines never touch
    the rest). Returns (sub_space, sub_evaluate, sub_default); sub_evaluate merges the held values back."""
    names = [p.name for p in space.parameters]
    editable = [n for n in (goal.editable or names) if n in names and n not in goal.fixed_params]
    held = {n: v for n, v in canonicalize(space, dict(start, **goal.fixed_params)).items() if n not in editable}
    sub = space.model_copy(update={"parameters": [p for p in space.parameters if p.name in editable]})
    sub_goal = goal.model_copy(update={"fixed_params": {}, "editable": None})

    def sub_evaluate(_space: DesignSpace, params: Dict[str, ParamValue], _goal: Goal):
        return evaluate(space, dict(held, **params), goal)

    default = {n: v for n, v in canonicalize(space, dict(start)).items() if n in editable}
    return sub, sub_evaluate, default, sub_goal

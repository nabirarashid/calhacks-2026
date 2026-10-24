"""Seeded GA used when the LLM proposer is unavailable or capped (origin "fallback").

Deliberately NOT CMA-ES, so the agent-vs-baseline comparison stays clean.
"""
import random
from typing import Dict, List

from shared.contracts import DesignSpace, Directive, ParamValue, Proposal

from backend.agents.base import RunHistory


def random_params(space: DesignSpace, rng: random.Random) -> Dict[str, ParamValue]:
    out = {}  # type: Dict[str, ParamValue]
    for p in space.parameters:
        if p.kind == "choice":
            out[p.name] = rng.choice(p.choices or [str(p.default)])
        elif p.kind == "integer":
            out[p.name] = rng.randint(int(p.min), int(p.max))  # type: ignore[arg-type]
        else:
            out[p.name] = rng.uniform(p.min, p.max)  # type: ignore[arg-type]
    return out


def mutate(space: DesignSpace, params: Dict[str, ParamValue], rng: random.Random, step_scale: float,
           focus: List[str]) -> Dict[str, ParamValue]:
    out = dict(params)
    for p in space.parameters:
        boost = 1.5 if p.name in focus else 1.0
        if p.kind == "choice":
            if rng.random() < 0.15 * boost:
                out[p.name] = rng.choice(p.choices or [str(p.default)])
        elif p.kind == "integer":
            if rng.random() < 0.15 * boost:
                out[p.name] = rng.randint(int(p.min), int(p.max))  # type: ignore[arg-type]
        elif rng.random() < 0.7 * boost:
            span = float(p.max) - float(p.min)  # type: ignore[arg-type]
            out[p.name] = float(out[p.name]) + rng.gauss(0.0, step_scale * boost * span)
    return out


def ga_propose(history: RunHistory, n: int, directive: Directive, rng: random.Random) -> List[Proposal]:
    space = history.space
    elites = [d for d in history.top(4)]
    props = []  # type: List[Proposal]
    n_novel = min(n, directive.n_explore) if elites else n
    for i in range(n):
        if i < n_novel or not elites:
            props.append(Proposal(params=random_params(space, rng), operator="novel",
                                  rationale="GA fallback: random exploration"))
        elif len(elites) >= 2 and rng.random() < 0.3:
            a, b = rng.sample(elites, 2)
            child = {k: (a.params[k] if rng.random() < 0.5 else b.params[k]) for k in a.params}
            props.append(Proposal(params=mutate(space, child, rng, directive.step_scale / 2, directive.focus_params),
                                  parent_ids=[a.design_id, b.design_id], operator="crossover",
                                  rationale="GA fallback: uniform crossover of two elites"))
        else:
            parent = elites[i % len(elites)]
            props.append(Proposal(params=mutate(space, parent.params, rng, directive.step_scale, directive.focus_params),
                                  parent_ids=[parent.design_id], operator="mutate",
                                  rationale="GA fallback: Gaussian mutation of an elite"))
    return props

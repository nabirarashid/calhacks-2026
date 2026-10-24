"""Pareto ranking over normalized objective scores."""

import math
from numbers import Real
from typing import Dict, List, Sequence

from shared.contracts import Goal, Score


def _objective_names(goal: Goal) -> List[str]:
    names = [objective.metric for objective in goal.objectives]
    if len(set(names)) != len(names):
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        raise ValueError(
            "goal contains duplicate objective metrics: %s"
            % ", ".join(repr(name) for name in duplicates)
        )
    return names


def _vectors(scores: Sequence[Score], names: Sequence[str]) -> Dict[int, List[float]]:
    result = {}  # type: Dict[int, List[float]]
    for index, score in enumerate(scores):
        vector = []  # type: List[float]
        for name in names:
            if name not in score.objective_scores:
                raise ValueError(
                    "score at index %d is missing objective score %r" % (index, name)
                )
            value = score.objective_scores[name]
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(
                    "score at index %d objective %r must be numeric; got %r"
                    % (index, name, value)
                )
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(
                    "score at index %d objective %r must be finite; got %r"
                    % (index, name, value)
                )
            if numeric < 0.0 or numeric > 1.0:
                raise ValueError(
                    "score at index %d objective %r must be in [0, 1]; got %s"
                    % (index, name, numeric)
                )
            vector.append(numeric)
        result[index] = vector
    return result


def _dominates(a: Sequence[float], b: Sequence[float]) -> bool:
    """Return whether higher-is-better vector *a* strictly dominates *b*."""
    return all(left >= right for left, right in zip(a, b)) and any(
        left > right for left, right in zip(a, b)
    )


def _rank_group(
    group: Sequence[int], vectors: Dict[int, List[float]], ranks: List[int], base: int
) -> int:
    """Rank one feasibility group and return the next unused rank."""
    remaining = list(group)
    rank = base
    while remaining:
        front = [
            index
            for index in remaining
            if not any(
                _dominates(vectors[other], vectors[index])
                for other in remaining
                if other != index
            )
        ]
        # A non-empty finite set always has at least one maximal element.  Keep
        # the guard explicit so malformed comparisons fail instead of looping.
        if not front:
            raise RuntimeError("failed to find a Pareto front for remaining scores")
        for index in front:
            ranks[index] = rank
        front_set = set(front)
        remaining = [index for index in remaining if index not in front_set]
        rank += 1
    return rank


def pareto_ranks(scores: List[Score], goal: Goal) -> List[int]:
    """Return non-dominated ranks using ``Score.objective_scores``.

    Every feasible front is ranked before any infeasible front.  Within each
    feasibility group, rank zero (or the group's base rank) is the ordinary
    non-dominated front.  If no feasible designs exist, the best infeasible
    designs correctly receive rank zero, matching the frozen mock behavior.
    """
    names = _objective_names(goal)
    vectors = _vectors(scores, names)
    ranks = [-1] * len(scores)

    feasible = [index for index, score in enumerate(scores) if score.feasible]
    infeasible = [index for index, score in enumerate(scores) if not score.feasible]
    next_rank = _rank_group(feasible, vectors, ranks, 0)
    _rank_group(infeasible, vectors, ranks, next_rank)
    return ranks


def pareto_front(scores: List[Score], goal: Goal) -> List[int]:
    """Return input indices on rank zero, preserving input order."""
    return [index for index, rank in enumerate(pareto_ranks(scores, goal)) if rank == 0]

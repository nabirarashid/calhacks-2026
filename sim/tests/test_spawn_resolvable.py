"""P1-B2: parallel evaluation is gated on spawn-resolvability, not on the fin.

The behaviour must be unchanged for the fin, and a dynamically registered
scorer (the backend's ScorerBridge for every non-fin project) must never be
sent to a process pool, because a spawned child cannot see it.
"""
import json
import os

import pytest

from shared.contracts import DesignSpace, Goal
from sim import api

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "fixtures")


def test_fin_is_spawn_resolvable():
    assert api.spawn_resolvable("fin_v1") is True


def test_unknown_scorer_is_not():
    assert api.spawn_resolvable("does_not_exist") is False


def test_dynamically_registered_scorer_is_not():
    class Plugin(object):
        def metric_catalog(self):
            return []

        def evaluate_metrics(self, *a, **k):
            raise AssertionError("never evaluated here")

    api.register_scorer("bridge:test_only", Plugin())
    try:
        assert api.spawn_resolvable("bridge:test_only") is False
    finally:
        api._SCORERS.pop("bridge:test_only", None)


def test_overriding_a_builtin_id_disables_the_pool():
    """A child would import the original plugin, not this replacement."""
    original = api._SCORERS.get("fin_v1")

    class Impostor(object):
        def metric_catalog(self):
            return []

        def evaluate_metrics(self, *a, **k):
            return None

    api.register_scorer("fin_v1", Impostor())
    try:
        assert api.spawn_resolvable("fin_v1") is False
    finally:
        if original is None:
            api._SCORERS.pop("fin_v1", None)
        else:
            api._SCORERS["fin_v1"] = original
    assert api.spawn_resolvable("fin_v1") is True


def test_process_safe_false_opts_a_builtin_out(monkeypatch):
    plugin = api._default_plugin("fin_v1")
    monkeypatch.setattr(plugin, "process_safe", False, raising=False)
    assert api.spawn_resolvable("fin_v1") is False


def test_bracket_bridge_batch_with_workers_runs_serially_and_correctly():
    """The regression this guards: workers > 0 on a bridged project must fall
    back to serial and still return correct scores, not crash a child."""
    from backend.adapters import ScorerBridge, get_solver, scorer_id
    from shared.manifest import ProjectManifest

    v2 = os.path.join(FIXTURES, "v2")
    with open(os.path.join(v2, "manifest_bracket.json")) as fh:
        m = ProjectManifest(**json.load(fh))
    with open(os.path.join(v2, "goal_bracket.json")) as fh:
        goal = Goal(**json.load(fh))

    sid = scorer_id(m)
    api.register_scorer(sid, ScorerBridge(m, get_solver("structural_analytic_v1")))
    try:
        space = m.design_space.model_copy(update={"scorer": sid})
        assert api.spawn_resolvable(sid) is False
        defaults = {p.name: p.default for p in space.parameters}
        batch = [dict(defaults, thickness=t) for t in (3.0, 5.0, 7.0)]
        serial = api.evaluate_batch(space, batch, goal, workers=0)
        pooled = api.evaluate_batch(space, batch, goal, workers=2)
        assert [s.metrics for s in pooled] == [s.metrics for s in serial]
        sfs = [s.metrics["safety_factor"] for s in serial]
        assert sfs == sorted(sfs), "thicker must be safer"
    finally:
        api._SCORERS.pop(sid, None)


def test_fin_parallel_matches_serial():
    """Behaviour preserved for the one scorer that does use the pool."""
    with open(os.path.join(FIXTURES, "design_space_fin.json")) as fh:
        space = DesignSpace(**json.load(fh))
    with open(os.path.join(FIXTURES, "goal_example.json")) as fh:
        goal = Goal(**json.load(fh))
    base = {p.name: p.default for p in space.parameters}
    batch = [dict(base, edge_profile="square", thickness=t) for t in (2.5, 4.0)]
    serial = api.evaluate_batch(space, batch, goal, workers=0)
    pooled = api.evaluate_batch(space, batch, goal, workers=2)
    assert [s.metrics for s in pooled] == [s.metrics for s in serial]

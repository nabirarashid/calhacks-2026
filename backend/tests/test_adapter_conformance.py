"""P1-8: every registered solver adapter passes the B.4 contract checks, and negative paths
return blocked/unsupported, never a pass. New adapters are covered automatically once registered."""
import math
import time

import pytest

from shared.contracts import AnalysisArtifact, Score
from shared.manifest import AdapterCapability, BlockingQuestion, CheckResult
from shared.mocks import make_fixtures_v2 as fx

from backend import adapters

# domain -> (draft manifest with nothing confirmed, solver-ready manifest, goal, a valid params dict)
CASES = {
    "static_structural": lambda: (fx.manifest_bracket(1), fx.manifest_bracket(3), fx.BRACKET_GOAL,
                                  {p.name: p.default for p in fx.manifest_bracket(3).design_space.parameters}),
}

IDS = sorted(adapters.SOLVERS)


def _case(adapter):
    cap = adapter.capability()
    if cap.domain not in CASES:
        pytest.skip("no conformance fixtures for domain %s yet" % cap.domain)
    return CASES[cap.domain]()


@pytest.mark.parametrize("adapter_id", IDS)
def test_capability_matches_catalog(adapter_id):
    a = adapters.get_solver(adapter_id)
    cap = a.capability()
    assert isinstance(cap, AdapterCapability) and cap.kind == "solver" and cap.adapter_id == adapter_id
    assert cap.metrics == [m.name for m in a.metric_catalog()]
    assert cap.fidelity and cap.validity_envelope


@pytest.mark.parametrize("adapter_id", IDS)
def test_missing_inputs_become_questions_and_evaluation_is_blocked(adapter_id):
    a = adapters.get_solver(adapter_id)
    draft, ready, goal, params = _case(a)
    questions = a.validate_manifest(draft)
    assert questions and all(isinstance(q, BlockingQuestion) for q in questions)
    with pytest.raises(ValueError):
        a.evaluate(draft, params, goal)              # blocked, never a fabricated pass
    assert a.validate_manifest(ready) == []


@pytest.mark.parametrize("adapter_id", IDS)
def test_evaluation_is_deterministic_complete_and_fast(adapter_id):
    a = adapters.get_solver(adapter_id)
    _, ready, goal, params = _case(a)
    t0 = time.perf_counter()
    s1, art = a.evaluate(ready, params, goal)
    elapsed = time.perf_counter() - t0
    s2, _ = a.evaluate(ready, params, goal)
    assert isinstance(s1, Score) and isinstance(art, AnalysisArtifact)
    assert s1.metrics == s2.metrics and s1.aggregate == s2.aggregate
    assert set(s1.metrics) == {m.name for m in a.metric_catalog()}
    assert all(math.isfinite(v) for v in s1.metrics.values())
    assert art.adapter_id == adapter_id and art.fidelity in a.capability().fidelity
    assert elapsed < 5.0, "screening evaluation must stay interactive"


@pytest.mark.parametrize("adapter_id", IDS)
def test_convergence_check_returns_a_check_result(adapter_id):
    a = adapters.get_solver(adapter_id)
    _, ready, _, params = _case(a)
    r = a.convergence_check(ready, params, "")
    assert isinstance(r, CheckResult) and r.passed in (True, False, None)


def test_unregistered_and_draft_adapters_never_load():
    with pytest.raises(KeyError):
        adapters.get_solver("thermal_fin_analytic_v1")
    with pytest.raises(ValueError):
        adapters.register_solver("evil", "sim.adapters.drafts.evil")

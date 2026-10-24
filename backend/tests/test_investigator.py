"""C2: the hypothesis-driven loop (PLAN.md B.3) on the rear wing, with mocks only."""
import pytest

from shared.contracts import GeometryRef, Goal
from shared.mocks.make_fixtures_v2 import WING_GOAL


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DARWIN_SIM", "real")
    monkeypatch.setenv("DARWIN_CAD", "off")
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FAKE_LLM_LATENCY", "0")
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path / ".darwin"))
    yield


def _inv(goal=WING_GOAL, **kw):
    from backend.bus import Bus
    from backend.investigator import Investigator
    from backend.wiring import Wiring
    w = Wiring()
    space = w.resolve("rear_wing")
    kw.setdefault("pack", w.packs.get("rear_wing"))
    return Investigator(w, Bus().open("session_test", record=False), space, goal, **kw)


def _run(inv, timeout=60):
    inv.start()
    inv.thread.join(timeout)
    assert not inv.thread.is_alive()
    return inv.ch.events


def test_full_session_respects_editable_limits_and_event_order():
    inv = _inv(max_steps=6, max_sims=14)
    events = _run(inv)
    types = [e["type"] for e in events]
    assert types[0] == "run_started" and types[-1] == "run_complete"
    seed = next(e["payload"]["design"] for e in events if e["type"] == "design_evaluated")
    for i, e in enumerate(events):
        if e["type"] == "design_evaluated" and e["payload"]["design"]["generation"] > 0:
            step = e["payload"]["design"]["generation"]
            planned = [j for j, x in enumerate(events) if x["type"] == "step_planned" and x["payload"]["step"] == step]
            assert planned and planned[0] < i, "every prediction is recorded before its simulation"
            changed = {k for k, v in e["payload"]["design"]["params"].items() if v != seed["params"][k]}
            assert changed <= set(WING_GOAL.editable) and "chord_mm" not in changed
    sims = sum(1 for t in types if t == "design_evaluated")
    assert sims <= 14
    final = events[-1]["payload"]["summary"]
    assert final["champion"]["score"]["feasible"]
    assert final["champion"]["score"]["metrics"]["downforce_n"] >= seed["score"]["metrics"]["downforce_n"]
    assert len([t for t in types if t == "step_result"]) == len([t for t in types if t == "notebook_updated"])


def test_plan_validation_rejects_bad_hypotheses():
    inv = _inv()
    inv.current = inv._evaluate(inv.start_params, 0, "seed", 0, "seed", "", [])
    ok = {"stop": False, "levers": ["span_mm"], "principle_ids": ["P-INDUCED-AR"], "rationale": "aspect ratio",
          "candidates": [{"settings": [{"param": "span_mm", "value": 950}]}],
          "predictions": [{"metric": "downforce_n", "direction": "up", "pct_low": 5, "pct_high": 15}]}
    hyp, _ = inv._validate_plan(ok, 1, 20)
    assert hyp.levers == ["span_mm"] and hyp.candidates[0]["chord_mm"] == inv.current.params["chord_mm"]
    bad = [
        dict(ok, levers=["chord_mm"]),                                                     # fixed
        dict(ok, candidates=[{"settings": [{"param": "span_mm", "value": 5000}]}]),        # out of bounds
        dict(ok, candidates=[{"settings": [{"param": "aoa_deg", "value": 8}]}]),           # not a lever
        dict(ok, predictions=[{"metric": "drag_n", "direction": "up", "pct_low": 1, "pct_high": 2}]),  # no goal metric
        dict(ok, predictions=[{"metric": "downforce_n", "direction": "up", "pct_low": -9, "pct_high": -1}]),
        dict(ok, candidates=[{"settings": [{"param": "span_mm", "value": inv.current.params["span_mm"]}]}]),  # seen
        dict(ok, stop=True, stop_reason="bored"),                                           # too early
    ]
    for b in bad:
        with pytest.raises(ValueError):
            inv._validate_plan(b, 1, 20)


def test_no_llm_falls_back_to_rules_and_still_finishes(monkeypatch):
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "replay")          # replay with an empty cache = unavailable
    events = _run(_inv(max_steps=4, max_sims=10))
    plans = [e["payload"] for e in events if e["type"] == "step_planned"]
    assert plans and all(p["source"] == "rules" for p in plans)
    assert events[-1]["type"] == "run_complete"
    assert any(d.startswith("rules@") for d in events[-1]["payload"]["summary"]["degradations"])


def test_knowledge_off_removes_principles(monkeypatch):
    monkeypatch.setenv("DARWIN_KNOWLEDGE", "off")
    inv = _inv(max_steps=2, max_sims=6)
    assert inv.principles == []
    events = _run(inv)
    assert all(e["payload"]["principle_ids"] == [] for e in events if e["type"] == "step_planned")


def test_apply_and_version_hooks_and_cad_failure_is_not_fatal():
    applied, versions = [], []

    def apply(space, params):
        applied.append(params)
        if len(applied) == 2:
            raise RuntimeError("onshape 500")
        return GeometryRef(geometry_key="k%d" % len(applied), status="ready", source="onshape_config")

    events = _run(_inv(max_steps=5, max_sims=12, apply=apply, version=lambda name: versions.append(name) or "v"))
    accepted = [e for e in events if e["type"] == "step_result" and e["payload"]["verdict"] == "accepted"]
    assert len(applied) == len(accepted) >= 1
    assert versions[0] == "Before Darwin" and versions[-1].startswith("Darwin:")
    assert events[-1]["type"] == "run_complete"
    if len(applied) >= 2:
        assert any("onshape_write_failed" in d for d in events[-1]["payload"]["summary"]["degradations"])


def test_analysis_numbers_are_claim_checked(monkeypatch):
    from backend import llm
    from shared.contracts import ModelResult
    real = llm.call_model

    def fake(role, *a, **k):
        if role == "investigator_analyze":
            return ModelResult(data={"explanation": "Downforce rose 99.9% thanks to magic.", "lesson": "Magic works."},
                               raw_text="", model="mock", provider="mock")
        return real(role, *a, **k)

    monkeypatch.setattr(llm, "call_model", fake)
    events = _run(_inv(max_steps=1, max_sims=4))
    result = next(e["payload"] for e in events if e["type"] == "step_result")
    assert "99.9" not in result["explanation"] and "[?]" in result["explanation"]


def test_consecutive_rejections_rule_a_lever_out():
    inv = _inv(goal=Goal.model_validate(dict(WING_GOAL.model_dump(), constraints=[
        {"ref": "drag_n", "op": "<=", "value": 12.03, "hard": True, "label": "drag cap at the baseline"}])),
        max_steps=6, max_sims=16)
    events = _run(inv)
    nb = [e["payload"] for e in events if e["type"] == "notebook_updated"][-1]
    results = [e["payload"] for e in events if e["type"] == "step_result"]
    for lever in nb["ruled_out"]:
        steps = [r for r in results if lever in next(e["payload"]["levers"] for e in events
                                                    if e["type"] == "step_planned" and e["payload"]["step"] == r["step"])]
        assert [r["verdict"] for r in steps][-2:] in (["rejected", "pivot"], ["pivot", "pivot"])

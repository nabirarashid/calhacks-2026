import json
from pathlib import Path

from shared.contracts import DesignSpace, MetricInfo

from domains import get_pack

from backend.agents.base import bind_pack
from backend.agents.goal_parser import to_goal

FIX = Path(__file__).resolve().parent.parent.parent / "shared" / "fixtures"
SPACE = DesignSpace.model_validate_json((FIX / "design_space_fin.json").read_text())
CATALOG = [MetricInfo.model_validate(m) for m in json.loads((FIX / "metric_catalog_fin.json").read_text())]
bind_pack(SPACE.id, get_pack("rocket_fin"))     # the body-tube rule is a rocket_fin domain rule
PITCH = "Maximize this rocket fin's stability, keep drag low, keep it under 40 g, must fit a 3-inch body tube."


def _llm(constraints):
    return {"objectives": [{"metric": "stability_margin_cal", "direction": "target", "target": 2.5,
                            "tolerance": 1.0, "weight": 0.5},
                           {"metric": "drag_n", "direction": "minimize", "weight": 0.5}],
            "constraints": [{"ref": "fin_mass_total_g", "op": "<=", "value": 40.0, "hard": True}] + constraints,
            "fixed_params": [], "design_velocity_mps": None, "assumptions": []}


def test_body_tube_misreadings_are_dropped_and_read_as_the_rocket_body():
    # The two real misreadings from live Haiku runs (Fri 23:31 and Sat 11:38).
    for bad in ({"ref": "param:semi_span", "op": "<=", "value": 38.1, "hard": True},
                {"ref": "param:root_chord", "op": "<=", "value": 76.2, "hard": True}):
        g = to_goal(_llm([bad]), PITCH, SPACE, CATALOG)
        refs = [c.ref for c in g.constraints]
        assert bad["ref"] not in refs
        assert ("aft_overhang_mm", "<=", 0.0) in [(c.ref, c.op, c.value) for c in g.constraints]
        assert "body_diameter_mm" not in g.context_overrides      # 3 in == the reference rocket already
        assert any("body" in a for a in g.assumptions)


def test_other_tube_sizes_override_the_body_diameter_and_keep_real_limits():
    real = {"ref": "param:semi_span", "op": "<=", "value": 60.0, "hard": True}
    g = to_goal(_llm([real]), "Light fins for a 4 inch body tube, span at most 60 mm", SPACE, CATALOG)
    assert g.context_overrides["body_diameter_mm"] == 101.6
    assert "param:semi_span" in [c.ref for c in g.constraints]


def test_no_tube_phrase_changes_nothing():
    g = to_goal(_llm([]), "Keep drag low and stay under 40 g", SPACE, CATALOG)
    assert "aft_overhang_mm" not in [c.ref for c in g.constraints]
    assert g.context_overrides == {}


def _wing():
    from backend.wiring import Wiring
    import os
    os.environ.setdefault("DARWIN_SIM", "real")
    w = Wiring()
    return w.resolve("rear_wing")


def test_editable_from_explicit_permission_and_keep():
    from backend.agents.goal_parser import resolve_editable
    space = _wing()
    ed, note = resolve_editable("More downforce under 15 N of drag. You can change the angle, span and flap. "
                                "Keep the mounts and endplates.", space, None, {})
    assert ed == ["aoa_deg", "span_mm", "flap_angle_deg"]             # "flap" alone = the flap angle
    assert "endplate_height_mm" in note and "chord_mm" in note        # both held fixed
    ed, _ = resolve_editable("Only change the flap angle.", space, None, {})
    assert ed == ["flap_angle_deg"]                                    # "flap angle" beats "flap" and "angle"
    ed, _ = resolve_editable("Make it more efficient but keep the chord and the span.", space, None, {})
    assert "chord_mm" not in ed and "span_mm" not in ed and "aoa_deg" in ed


def test_llm_suggestion_used_only_without_explicit_phrases_and_never_overrides_keep():
    from backend.agents.goal_parser import resolve_editable
    space = _wing()
    ed, _ = resolve_editable("Tweak whatever helps the tip vortex; leave the chord alone.", space,
                             ["endplate_height_mm", "chord_mm"], {})
    assert ed == ["endplate_height_mm"]                                # chord was kept
    ed, _ = resolve_editable("You can change the span.", space, ["aoa_deg", "flap_angle_deg"], {})
    assert ed == ["span_mm"]                                           # explicit phrase wins over the LLM
    ed, note = resolve_editable("More downforce please.", space, None, {})
    assert ed is None and "every parameter" in note


def test_fin_prompts_use_the_fin_aliases():
    from backend.agents.goal_parser import resolve_editable
    from backend.wiring import Wiring
    space = Wiring().resolve("fin_reference")
    ed, _ = resolve_editable("Make it lighter, but keep the span and the sweep.", space, None, {})
    assert "semi_span" not in ed and "sweep_deg" not in ed and "thickness" in ed
    ed, _ = resolve_editable(PITCH, space, None, {})                   # "keep drag low", "keep it under 40 g"
    assert ed is None


def test_invented_pins_are_dropped_and_stated_pins_kept():
    space = _wing()
    from backend.wiring import Wiring
    cat = Wiring().catalog(space.scorer)
    text = "More downforce under 15 N of drag. You can change the angle and span. Keep the endplates."
    data = {"objectives": [{"metric": "downforce_n", "direction": "maximize", "weight": 1}],
            "constraints": [{"ref": "drag_n", "op": "<=", "value": 15, "hard": True}],
            "fixed_params": [{"name": "endplate_height_mm", "value": "300"}],      # invented by the model
            "assumptions": ["endplate_height_mm pinned at 300 mm."], "editable": []}
    g = to_goal(data, text, space, cat)
    assert g.fixed_params == {} and "endplate_height_mm" not in (g.editable or [])
    assert not any("300" in a for a in g.assumptions)
    stated = dict(data, fixed_params=[{"name": "aoa_deg", "value": "8"}])
    g2 = to_goal(stated, text + " Start with the angle at 8 degrees.", space, cat)
    assert g2.fixed_params == {"aoa_deg": 8.0}


def test_no_llm_fallback_for_the_wing_reads_numbers_and_editable(monkeypatch):
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "replay")              # replay with an empty cache = no LLM
    monkeypatch.setenv("DARWIN_SIM", "real")
    from backend.agents.goal_parser import parse_goal
    from backend.wiring import Wiring
    w = Wiring()
    space = w.resolve("rear_wing")
    g, res = parse_goal("More downforce without going over 13.5 N of drag. You can change the angle and span.",
                        space, w.catalog(space.scorer), w.presets)
    assert res is None and g.parsed_by == "fallback"
    assert [o.metric for o in g.objectives] == ["downforce_n"]
    assert ("drag_n", "<=", 13.5) in [(c.ref, c.op, c.value) for c in g.constraints]
    assert g.editable == ["aoa_deg", "span_mm"] and "Darwin may change" in g.assumptions[0]
    g2, _ = parse_goal("Cut drag but keep at least 130 N of downforce.", space, w.catalog(space.scorer), w.presets)
    assert [o.metric for o in g2.objectives] == ["drag_n"]
    assert ("downforce_n", ">=", 130.0) in [(c.ref, c.op, c.value) for c in g2.constraints]

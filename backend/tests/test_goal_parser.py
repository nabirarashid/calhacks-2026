import json
from pathlib import Path

from shared.contracts import DesignSpace, MetricInfo

from backend.agents.goal_parser import to_goal

FIX = Path(__file__).resolve().parent.parent.parent / "shared" / "fixtures"
SPACE = DesignSpace.model_validate_json((FIX / "design_space_fin.json").read_text())
CATALOG = [MetricInfo.model_validate(m) for m in json.loads((FIX / "metric_catalog_fin.json").read_text())]
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

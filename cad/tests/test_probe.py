import pytest

from cad.probe import generate_cases, probe, probe_cache_key


PARAMS = [
    {"name": "width", "min": 2, "max": 8, "role": "editable"},
    {"name": "fixed", "min": 1, "max": 3, "role": "fixed"},
    {"name": "height", "min": 4, "max": 10, "role": "editable"},
]


def test_generates_seed_and_extremes_within_nine():
    cases = generate_cases(PARAMS, {"width": 4, "height": 7})
    assert [r["case"] for r in cases] == ["seed", "min:width", "max:width", "min:height", "max:height"]
    assert len(generate_cases(PARAMS * 5, {"width": 4}, limit=9)) == 9
    with pytest.raises(ValueError):
        generate_cases(PARAMS, {}, limit=10)


def test_probe_classifies_failures_range_units_and_scale_and_caches():
    calls = []
    values = {4: {"status": "ready", "units": "mm", "bbox_mm": [0, 0, 0, 10, 10, 10]},
              2: {"status": "out_of_range"},
              8: {"status": "failed", "error": "regen"},
              6: {"status": "ready", "units": "inch"}}

    def regenerate(params):
        calls.append(dict(params))
        w = params["width"]
        if w == 4:
            return values[4]
        if w == 2:
            return values[2]
        if w == 8:
            return values[8]
        return values[6]

    cache = {}
    rows = probe([{"name": "width", "min": 2, "max": 8}], {"width": 4},
                 regenerate, cache=cache)
    assert len(rows) == 3 <= 9
    assert [r["evidence"]["failure_reason"] for r in rows] == [None, "out_of_range", "regeneration_failed"]
    second = probe([{"name": "width", "min": 2, "max": 8}], {"width": 4},
                   regenerate, cache=cache)
    assert all(r["evidence"]["cached"] for r in second)
    assert len(calls) == 3


def test_probe_detects_bad_units_and_scale():
    rows = probe([{"name": "w", "min": 1, "max": 1}], {"w": 1},
        lambda p: {"status": "ready", "units": "inch", "bbox_mm": [0, 0, 0, 1, 1, 1]})
    assert rows[0]["evidence"]["failure_reason"] == "wrong_units_or_scale"


def test_probe_cache_key_changes_with_revision():
    assert probe_cache_key({"width": 2}, "project:space:r1:mv1") != probe_cache_key(
        {"width": 2}, "project:space:r2:mv1")
    assert probe_cache_key({"width": 2}, "project:space:r1:mv1") != probe_cache_key(
        {"width": 2}, "project:space:r1:mv2")


def test_skipped_regeneration_does_not_poison_cache():
    cache = {}
    probe([], {"width": 2}, lambda _p: {"status": "skipped", "error": "budget"},
          cache=cache)
    assert cache == {}
    rows = probe([], {"w": 1}, lambda p: {"status": "ready", "bbox_mm": [0, 0, 0, 1e8, 1, 1]})
    assert rows[0]["evidence"]["failure_reason"] == "wrong_units_or_scale"

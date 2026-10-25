"""The geometry check on measured-looking data (numbers from the live wing, Sat/Sun)."""
from backend.geometry_check import compare

ROLES = {"M": "wing", "F": "wing", "E1": "endplate", "E2": "endplate"}


def m(width=850.0, z=45.8, main=4.68e6, flap=1.74e6, ep=3.36e5, flap_z=0.0):
    # overall box = the endplates (they enclose the wing and sit 5 mm outside the span)
    return {"bbox": [-168.0, -width / 2 - 5, -100.0, 168.0, width / 2 + 5, 100.0],
            "volumes": {"M": main, "F": flap, "E1": ep, "E2": ep}, "roles": ROLES,
            "parts": {"M": [-139.0, -width / 2, -16.0, 57.0, width / 2, z - 16.0],
                      "F": [57.0, -width / 2, -20.0 - flap_z, 139.0, width / 2, 8.0]}}


def test_consistent_steps_pass():
    p = {"span_mm": 950.0, "endplate_height_mm": 200.0}
    assert compare(m(), m(width=950.0, main=5.23e6, flap=1.94e6), {"span_mm": 850.0}, {"span_mm": 950.0}, p) == ([], [])
    p = {"span_mm": 850.0, "endplate_height_mm": 280.0}
    assert compare(m(), m(ep=4.704e5), {"endplate_height_mm": 200.0}, {"endplate_height_mm": 280.0}, p) == ([], [])


def test_a_parameter_the_cad_ignores_is_flagged():
    # the chord bug: chord 280 -> 330 written, nothing in Onshape moved
    problems, dead = compare(m(), m(), {"chord_mm": 280.0}, {"chord_mm": 330.0}, {"span_mm": 850.0})
    assert dead == ["chord_mm"] and problems == []


def test_span_and_endplate_mismatches_are_reported():
    problems, dead = compare(m(), m(width=850.0, z=50.0), {"span_mm": 850.0, "aoa_deg": 6.0},
                             {"span_mm": 950.0, "aoa_deg": 8.0}, {"span_mm": 950.0})
    assert dead == [] and "950" in problems[0]
    problems, _ = compare(m(), m(ep=3.5e5), {"endplate_height_mm": 200.0}, {"endplate_height_mm": 280.0},
                          {"span_mm": 850.0})
    assert "Endplates" in problems[0]


def test_a_rotating_flap_inside_the_endplates_is_not_mistaken_for_a_dead_parameter():
    # live Sun 02:10: rotation keeps every volume and the overall (endplate) box; only the flap's box moves
    problems, dead = compare(m(), m(flap_z=6.0), {"flap_angle_deg": 13.5}, {"flap_angle_deg": 16.5}, {"span_mm": 850.0})
    assert (problems, dead) == ([], [])

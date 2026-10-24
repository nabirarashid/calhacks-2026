import json
from pathlib import Path

import pytest

from shared import fin_geometry
from shared.check import main as check_main
from shared.contracts import DesignSpace, canonicalize, geometry_key, param_hash

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
SPACE = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())


def test_fixtures_validate():
    assert check_main() == 0


def test_canonicalize_fills_clamps_rounds():
    c = canonicalize(SPACE, {"root_chord": 91.26, "semi_span": 500, "fin_count": 3.4})
    assert c["root_chord"] == 91.5          # step 0.5
    assert c["semi_span"] == 90.0           # clamped to max
    assert c["fin_count"] == 3 and isinstance(c["fin_count"], int)
    assert c["edge_profile"] == "rounded"   # default filled
    assert list(c) == [p.name for p in SPACE.parameters]


def test_canonicalize_rejects_bad_input():
    with pytest.raises(ValueError):
        canonicalize(SPACE, {"wingspan": 3})
    with pytest.raises(ValueError):
        canonicalize(SPACE, {"edge_profile": "airfoil"})
    with pytest.raises(ValueError):
        canonicalize(SPACE, {"thickness": float("nan")})


def test_hashes_stable_and_geometry_key_ignores_sim_only():
    a = {"root_chord": 90.0, "fin_count": 3}
    b = {"root_chord": 90.04, "fin_count": 4}   # rounds to the same chord
    assert param_hash(SPACE, a) != param_hash(SPACE, b)
    assert geometry_key(SPACE, a) == geometry_key(SPACE, b)
    assert param_hash(SPACE, a) == param_hash(SPACE, dict(a))


def test_fin_geometry_rectangle():
    p = {"root_chord": 90, "taper_ratio": 1.0, "semi_span": 60, "sweep_deg": 0, "thickness": 3,
         "edge_profile": "square"}
    d = fin_geometry.derived(p)
    assert d["area_mm2"] == pytest.approx(5400)
    assert d["volume_mm3"] == pytest.approx(16200)
    assert d["volume_mm3"] / 1000 * 1.24 == pytest.approx(20.09, abs=0.01)   # PLAN S2 units test
    assert fin_geometry.bbox_mm(p) == pytest.approx([0, -1.5, 0, 90, 1.5, 60])


def test_prism_stl_volume_matches():
    p = json.loads((FIXTURES / "design_result_example.json").read_text())["params"]
    p = dict(p, edge_profile="square")
    stl = fin_geometry.prism_stl(p)
    assert stl.count("facet normal") == 12
    import re
    v = [tuple(map(float, m)) for m in re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", stl)]
    vol = 0.0
    for i in range(0, len(v), 3):
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = v[i], v[i + 1], v[i + 2]
        vol += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)) / 6.0
    assert vol == pytest.approx(fin_geometry.derived(p)["volume_mm3"], rel=1e-6)

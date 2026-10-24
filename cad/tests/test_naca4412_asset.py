import importlib.util
import math
from pathlib import Path

import pytest


CAD_DIR = Path(__file__).resolve().parents[1]
ASSET = CAD_DIR / "assets" / "naca4412_inverted_unit.dxf"
R12_ASSET = CAD_DIR / "assets" / "naca4412_inverted_unit_r12.dxf"
SCRIPT = CAD_DIR / "generate_naca4412.py"


def _read_polyline(path):
    lines = path.read_text(encoding="ascii").splitlines()
    assert len(lines) % 2 == 0
    pairs = list(zip(lines[::2], lines[1::2]))
    assert ("0", "LWPOLYLINE") in pairs
    assert ("0", "EOF") in pairs
    closed = False
    points = []
    i = pairs.index(("0", "LWPOLYLINE")) + 1
    while i < len(pairs) and pairs[i] != ("0", "ENDSEC"):
        code, value = pairs[i]
        if code == "70":
            closed = bool(int(value) & 1)
        if code == "10":
            x = float(value)
            assert pairs[i + 1][0] == "20"
            points.append((x, float(pairs[i + 1][1])))
            i += 1
        i += 1
    return closed, points


def test_checked_in_profile_is_closed_finite_and_unit_chord():
    closed, points = _read_polyline(ASSET)
    assert closed
    assert len(points) >= 150
    assert points[0] == points[-1]
    assert all(math.isfinite(v) for point in points for v in point)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    assert abs(max(xs) - 1.0) < 1e-9
    assert min(xs) > -0.01
    assert max(ys) - min(ys) == pytest.approx(0.12, abs=0.01)
    assert sum(y for x, y in points if abs(x - 0.5) < 0.005) / len(
        [y for x, y in points if abs(x - 0.5) < 0.005]
    ) < 0
    assert abs(points[0][0]) < 1e-9
    assert abs(points[80][0] - 1.0) < 1e-9


def test_script_deterministically_recreates_asset(tmp_path):
    spec = importlib.util.spec_from_file_location("generate_naca4412", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated = tmp_path / "profile.dxf"
    with generated.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(module.dxf_text(module.profile_points()))
    assert generated.read_bytes() == ASSET.read_bytes()


def _read_r12(path):
    lines = path.read_text(encoding="ascii").splitlines()
    pairs = list(zip(lines[::2], lines[1::2]))
    assert ("9", "$ACADVER") in pairs
    assert ("1", "AC1009") in pairs
    entities = []
    i = 0
    while i < len(pairs):
        if pairs[i] == ("0", "LINE"):
            fields = dict(pairs[i + 1:i + 8])
            entities.append(((float(fields["10"]), float(fields["20"])),
                             (float(fields["11"]), float(fields["21"]))))
            i += 7
        i += 1
    return entities


def test_r12_asset_has_shared_endpoint_closed_line_loop_and_same_profile(tmp_path):
    entities = _read_r12(R12_ASSET)
    assert len(entities) == 161
    assert all(entities[i][1] == entities[(i + 1) % len(entities)][0]
               for i in range(len(entities)))
    points = [segment[0] for segment in entities] + [entities[-1][1]]
    assert all(math.isfinite(v) for point in points for v in point)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    assert abs(max(xs) - 1.0) < 1e-9 and min(xs) > -0.01
    assert max(ys) - min(ys) == pytest.approx(0.12, abs=0.01)
    mid = [y for x, y in points if abs(x - 0.5) < 0.005]
    assert sum(mid) / len(mid) < 0
    spec = importlib.util.spec_from_file_location("generate_naca4412_r12", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    generated = tmp_path / "profile_r12.dxf"
    with generated.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(module.r12_dxf_text(module.profile_points()))
    assert generated.read_bytes() == R12_ASSET.read_bytes()

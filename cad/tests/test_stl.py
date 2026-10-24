"""STL parsing, measurement and sanity-check tests. Zero network."""
import json
import os
import struct

import pytest

from cad import stl
from shared import fin_geometry

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "..",
                        "shared", "fixtures", "geometry")

SQUARE = {"root_chord": 90.0, "taper_ratio": 0.5, "semi_span": 60.0,
          "sweep_deg": 30.0, "thickness": 3.0, "edge_profile": "square"}


def _fixture_pairs():
    out = []
    for name in sorted(os.listdir(FIXTURES)):
        if name.endswith(".stl"):
            side = os.path.join(FIXTURES, name[:-4] + ".json")
            if os.path.exists(side):
                out.append((os.path.join(FIXTURES, name), side))
    return out


def test_fixtures_exist():
    assert len(_fixture_pairs()) >= 5, "expected recorded STL fixtures in shared/fixtures/geometry"


@pytest.mark.parametrize("stl_path,side_path", _fixture_pairs())
def test_fixture_measurements_match_sidecar(stl_path, side_path):
    """Our parser must reproduce the measurements fake_cad recorded."""
    with open(side_path) as fh:
        ref = json.load(fh)
    with open(stl_path, "rb") as fh:
        mesh = stl.parse(fh.read())

    assert mesh.triangle_count == ref["triangles"]
    for want, got in zip(ref["bbox_mm"], mesh.bbox()):
        assert abs(got - want) < 1e-3, "bbox %r vs %r" % (ref["bbox_mm"], mesh.bbox())
    assert abs(mesh.volume_mm3() - ref["volume_mm3"]) / ref["volume_mm3"] < 1e-4


def test_ascii_roundtrip_matches_analytic():
    """prism_stl -> parse -> measurements agree with the frozen formulas."""
    mesh = stl.parse(fin_geometry.prism_stl(SQUARE))
    assert mesh.triangle_count == 12
    for want, got in zip(fin_geometry.bbox_mm(SQUARE), mesh.bbox()):
        assert abs(got - want) < 1e-6
    want_vol = fin_geometry.derived(SQUARE)["volume_mm3"]
    assert abs(mesh.volume_mm3() - want_vol) / want_vol < 1e-6


def test_sanity_check_passes_on_matching_geometry():
    mesh = stl.parse(fin_geometry.prism_stl(SQUARE))
    ok, reasons = stl.sanity_check(SQUARE, mesh)
    assert ok, reasons


def test_sanity_check_fails_on_stale_geometry():
    """The STL of a *different* design must be rejected — this is the guard
    against Onshape returning the previous configuration with HTTP 200."""
    other = dict(SQUARE)
    other["root_chord"] = 130.0
    other["semi_span"] = 90.0
    mesh = stl.parse(fin_geometry.prism_stl(other))
    ok, reasons = stl.sanity_check(SQUARE, mesh)
    assert not ok
    assert any("bbox" in r for r in reasons)


def test_sanity_check_catches_unit_scale_error():
    """A metre-scaled export (x1000) must fail, not silently pass."""
    text = fin_geometry.prism_stl(SQUARE)
    scaled = []
    for line in text.splitlines():
        parts = line.strip().split()
        if parts and parts[0] == "vertex":
            vals = [float(v) / 1000.0 for v in parts[1:4]]
            scaled.append("      vertex %.6e %.6e %.6e" % tuple(vals))
        else:
            scaled.append(line)
    mesh = stl.parse("\n".join(scaled))
    ok, reasons = stl.sanity_check(SQUARE, mesh)
    assert not ok
    assert reasons


def test_binary_roundtrip():
    """Binary STL must measure identically to the same mesh in ASCII."""
    ascii_mesh = stl.parse(fin_geometry.prism_stl(SQUARE))
    blob = b"\0" * 80 + struct.pack("<I", ascii_mesh.triangle_count)
    for tri in ascii_mesh.triangles:
        blob += struct.pack("<3f", 0.0, 0.0, 0.0)
        for v in tri:
            blob += struct.pack("<3f", v[0], v[1], v[2])
        blob += struct.pack("<H", 0)
    mesh = stl.parse(blob)
    assert mesh.triangle_count == ascii_mesh.triangle_count
    for want, got in zip(ascii_mesh.bbox(), mesh.bbox()):
        assert abs(got - want) < 1e-3
    assert abs(mesh.volume_mm3() - ascii_mesh.volume_mm3()) / ascii_mesh.volume_mm3() < 1e-5


def test_rejects_garbage():
    with pytest.raises(stl.StlParseError):
        stl.parse(b"not an stl at all")
    with pytest.raises(stl.StlParseError):
        stl.parse("solid empty\nendsolid empty\n")


def test_measure_reports_regen_status():
    out = stl.measure(SQUARE, fin_geometry.prism_stl(SQUARE))
    assert out["regen_status"] == "OK"
    assert out["triangles"] == 12
    assert out["sanity_reasons"] == []

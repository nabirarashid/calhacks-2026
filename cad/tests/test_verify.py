import pytest
from pathlib import Path

from cad import verify
from domains.static_structural.verifier import StaticStructuralGeometryVerifier
from shared import fin_geometry


PARAMS = {"root_chord": 90.0, "taper_ratio": 0.5, "semi_span": 60.0,
          "sweep_deg": 30.0, "thickness": 3.0, "edge_profile": "square"}


def test_generic_verifier_accepts_watertight_mm_mesh():
    data = fin_geometry.prism_stl(PARAMS)
    result = verify.verify(data, expected_bbox_mm=fin_geometry.bbox_mm(PARAMS))
    assert result["ok"]
    assert result["checks"]["watertight"]["ok"]
    assert result["checks"]["mm_scale"]["ok"]
    assert result["parts"] == 1


def test_generic_verifier_flags_wrong_scale_and_empty_stl():
    data = fin_geometry.prism_stl(PARAMS)
    scaled = "\n".join(
        "vertex " + " ".join(str(float(v) / 1000) for v in line.split()[1:])
        if line.strip().startswith("vertex ") else line
        for line in data.splitlines())
    assert not verify.verify(scaled, expected_bbox_mm=fin_geometry.bbox_mm(PARAMS))["ok"]
    with pytest.raises(ValueError):
        verify.verify("solid empty\nendsolid empty")


def test_generic_verifier_flags_nonmanifold_mesh():
    data = fin_geometry.prism_stl(PARAMS)
    lines = data.splitlines()
    vertices = [line for line in lines if line.strip().startswith("vertex ")]
    # Removing one facet creates open boundary edges.
    first_facet = data.index("facet normal")
    next_facet = data.index("facet normal", first_facet + 1)
    broken = data[:first_facet] + data[next_facet:]
    assert not verify.verify(broken)["checks"]["watertight"]["ok"]


def test_cad_python_sources_do_not_import_domain_or_shared_fin_geometry():
    root = Path(__file__).resolve().parents[1]
    banned = ("shared.fin_" + "geometry", "domains.rocket_" + "fin",
              "FinGeometry" + "Verifier", "fin_" + "v" + "1",
              "fin_" + "geo" + "metry")
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in banned), "%s contains CAD domain coupling" % path


def test_generic_verifier_accepts_explicit_mm_export_units_without_bbox():
    result = verify.verify(fin_geometry.prism_stl(PARAMS), units="millimeter")
    assert result["ok"]
    assert result["checks"]["mm_scale"] == {
        "ok": True, "basis": "trusted export units"}


def test_static_verifier_checks_injected_connector_and_hole_measurements(tmp_path):
    path = tmp_path / "bracket.stl"
    path.write_text(fin_geometry.prism_stl(PARAMS))
    manifest = type("Manifest", (), {"protected": [
        {"id": "mount_hole_a", "cad_ref": "mount_hole_a", "kind": "hole",
         "check": "position", "nominal": {"x": 10.0, "y": 20.0, "z": 0.0},
         "tolerance_mm": 0.05},
        {"id": "load_hole", "cad_ref": "load_hole", "kind": "hole",
         "check": "diameter", "nominal": {"d": 5.0}, "tolerance_mm": 0.05},
    ]})()
    verifier = StaticStructuralGeometryVerifier(
        inventory={"mate_connectors": [{"name": "mount_hole_a",
                                         "origin_mm": [10.01, 20.0, 0.0]}]},
        hole_measurements={"load_hole": {"diameter_mm": 5.02,
                                           "evidence": "exported_geometry"}},
    )

    result = verifier.verify(manifest, {}, str(path))

    assert result["ok"]
    assert all(check["ok"] for check in result["protected_interfaces"])


def test_static_verifier_fails_closed_without_interface_measurements(tmp_path):
    path = tmp_path / "bracket.stl"
    path.write_text(fin_geometry.prism_stl(PARAMS))
    manifest = type("Manifest", (), {"protected": [
        {"id": "mount_hole_a", "cad_ref": "mount_hole_a", "kind": "hole",
         "check": "position", "nominal": {"x": 10.0, "y": 20.0, "z": 0.0}},
    ]})()

    result = StaticStructuralGeometryVerifier().verify(manifest, {}, str(path))

    assert not result["ok"]
    assert result["protected_interfaces"][0]["ok"] is None


def test_static_verifier_binds_manifest_for_in_memory_build_checks():
    manifest = {"protected": []}
    verifier = StaticStructuralGeometryVerifier().bind(manifest)

    result = verifier.verify_data({}, fin_geometry.prism_stl(PARAMS))

    assert result["ok"]
    assert result["reasons"] == []

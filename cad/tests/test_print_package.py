import json
import zipfile

import pytest

from cad import api, cache
from shared.contracts import DesignSpace, canonicalize, geometry_key


def fixture_space():
    with open("shared/fixtures/design_space_fin.json") as stream:
        return DesignSpace.model_validate_json(stream.read())


def test_export_writes_stable_stl_and_json_label(tmp_path, monkeypatch):
    space = fixture_space()
    params = {p.name: p.default for p in space.parameters}
    key = geometry_key(space, canonicalize(space, params))
    source = tmp_path / (key + ".stl")
    source.write_text("solid mm\nendsolid mm\n")
    monkeypatch.setattr(api, "build_geometry", lambda s, p, **kwargs: type("Ref", (), {
        "status": "ready", "geometry_key": key, "error": None})())
    monkeypatch.setattr(cache, "stl_path", lambda k: str(source))

    result = api.export_print_package(space, params, str(tmp_path / "out"),
                                      design_id="run-01-g00-a00", score={"aggregate": 0.8})
    with zipfile.ZipFile(result) as bundle:
        assert bundle.namelist() == ["design.stl", "label.json"]
        label = json.loads(bundle.read("label.json"))
        assert label["geometry_key"] == key
        assert label["design_id"] == "run-01-g00-a00"
        assert label["units"] == "mm"
        assert bundle.read("design.stl") == source.read_bytes()
    first = open(result, "rb").read()
    api.export_print_package(space, params, str(tmp_path / "out"),
                             design_id="run-01-g00-a00", score={"aggregate": 0.8})
    assert open(result, "rb").read() == first


def test_export_requires_label_metadata(tmp_path):
    with pytest.raises(ValueError, match="design_id"):
        api.export_print_package(fixture_space(), {}, str(tmp_path))


def test_export_fails_closed_when_geometry_not_ready(tmp_path, monkeypatch):
    space = fixture_space()
    monkeypatch.setattr(api, "build_geometry", lambda s, p, **kwargs: type("Ref", (), {
        "status": "failed", "geometry_key": "x", "error": "failed"})())
    with pytest.raises(RuntimeError, match="geometry is not ready"):
        api.export_print_package(space, {p.name: p.default for p in space.parameters},
                                 str(tmp_path), design_id="d", score={"aggregate": 0.5})

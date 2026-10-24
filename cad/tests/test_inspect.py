import json

from cad.inspect import parse_inventory, save_sanitized_raw, sanitize_payload


def fixture():
    return {
        "elements": [{"name": "Main", "documentId": "secret-doc", "elementId": "secret-el"}],
        "units": {"length": "mm"},
        "configuration": {
            "sourceMicroversion": "mv-abc",
            "configurationParameters": [{"parameterId": "width", "parameterName": "Width",
                "rangeAndDefault": {"minValue": 2, "maxValue": 8, "defaultValue": 4, "units": "mm"}}],
            "currentConfiguration": [{"parameterId": "width", "value": 4, "units": "mm"}],
        },
        "features": {"sourceMicroversion": "mv-abc", "features": [
            {"featureId": "F1", "name": "Base", "featureType": "extrude"},
            {"featureId": "M1", "name": "mount_hole_a", "featureType": "mateConnector",
             "origin_mm": [1, 2, 3]}]},
        "parts": [{"partId": "P1", "name": "Bracket", "bbox_mm": [0, 0, 0, 10, 20, 30]}],
        "mass_properties": {"P1": {"mass_g": 12.5, "volume_mm3": 6000}},
    }


def test_parses_inventory_sections_and_mate_connectors():
    inv = parse_inventory(fixture(), onshape_calls=5)
    assert inv["source_microversion"] == "mv-abc"
    assert inv["config_inputs"][0] == {"id": "width", "name": "Width", "kind": "quantity",
        "unit": "mm", "min": 2, "max": 8, "default": 4, "choices": []}
    assert inv["parts"][0]["mass_g"] == 12.5
    assert inv["parts"][0]["volume_mm3"] == 6000
    assert inv["mate_connectors"][0]["origin_mm"] == [1, 2, 3]
    assert inv["onshape_calls"] == 5


def test_sanitizer_redacts_ids_and_secrets_in_saved_raw(tmp_path):
    data = fixture()
    data["credentials"] = {"access_key": "dont-save"}
    safe = sanitize_payload(data)
    assert safe["elements"][0]["documentId"] == "[redacted]"
    assert safe["configuration"]["sourceMicroversion"] == "[redacted]"
    assert safe["credentials"]["access_key"] == "[redacted]"
    path = tmp_path / "raw.json"
    save_sanitized_raw(data, str(path))
    text = path.read_text()
    assert "secret-doc" not in text
    assert "mv-abc" not in text
    assert "dont-save" not in text
    assert json.loads(text)["elements"][0]["elementId"] == "[redacted]"


def test_inspect_rejects_call_budget_over_six():
    import pytest
    with pytest.raises(ValueError, match="six"):
        parse_inventory(fixture(), onshape_calls=7)


def test_parses_nested_onshape_shapes_and_converts_si_mass_properties():
    payload = {
        "configuration": {
            "sourceMicroversion": "mv",
            "configurationParameters": [{"message": {
                "parameterId": "size", "parameterName": "Size",
                "defaultValue": "small", "options": [
                    {"optionName": "Small", "option": "small"},
                    {"optionName": "Large", "option": "large"},
                ],
            }}],
            "currentConfiguration": [{"parameterId": "size", "value": "small"}],
        },
        "features": {"features": [{"feature": {"message": {
            "featureId": "M1", "name": "mount_hole_a", "featureType": "mateConnector",
        }}}]},
        "parts": [{"partId": "P1", "name": "Bracket", "boundingBox": {
            "minX": 0, "minY": 0, "minZ": 0, "maxX": .01, "maxY": .02, "maxZ": .03,
        }}],
        "mass_properties": {"bodies": {"P1": {
            "mass": [0.0125, 0.0124, 0.0126],
            "volume": [0.000006, 0.0000059, 0.0000061],
        }}},
    }

    inv = parse_inventory(payload, onshape_calls=5)

    assert inv["config_inputs"][0]["choices"] == ["Small", "Large"]
    assert inv["mate_connectors"][0]["origin_mm"] is None
    assert inv["parts"][0]["mass_g"] == 12.5
    assert inv["parts"][0]["volume_mm3"] == 6000.0
    assert inv["parts"][0]["bbox_mm"] == [0, 0, 0, 10, 20, 30]

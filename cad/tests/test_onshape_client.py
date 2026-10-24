"""Pure tests for safely constructing and checking configuration updates."""
import copy

import pytest

from cad.onshape_client import (build_configuration_update, configuration_values,
                                parse_workspace_url, verify_configuration_update)


def configuration():
    names = ["root_chord", "taper_ratio", "semi_span", "sweep_deg", "thickness"]
    values = [90.0, 0.5, 60.0, 30.0, 3.0]
    units = ["millimeter", "unitless", "millimeter", "degree", "millimeter"]
    ranges = [(50, 130), (0.2, 1.0), (30, 90), (0, 60), (2, 5)]
    return {
        "btType": "BTConfigurationResponse-2019",
        "serializationVersion": "1.2.2",
        "libraryVersion": 181,
        "sourceMicroversion": "microversion-before",
        "microversionSkew": False,
        "customMetadata": {"keep": True},
        "configurationParameters": [
            {
                "btType": "BTMConfigurationParameterQuantity-1826",
                "parameterId": name,
                "rangeAndDefault": {
                    "btType": "BTMParameterQuantityRangeAndDefault-2861",
                    "minValue": low,
                    "maxValue": high,
                    "defaultValue": value,
                    "units": unit,
                    "customRangeField": "preserve",
                },
            }
            for name, value, unit, (low, high) in zip(names, values, units, ranges)
        ],
        "currentConfiguration": [
            {"parameterId": name, "value": value,
             "expression": str(value) + (" mm" if unit == "millimeter" else " deg" if unit == "degree" else ""),
             "units": unit, "extra": "preserve"}
            for name, value, unit in zip(names, values, units)
        ],
    }


def test_builds_quantity_only_update_and_preserves_unmodified_fields():
    original = configuration()
    original_copy = copy.deepcopy(original)
    update = build_configuration_update(original, {"root_chord": 92, "sweep_deg": 35})

    assert original == original_copy
    assert update["btType"] == "BTConfigurationUpdateCall-2933"
    assert update["rejectMicroversionSkew"] is True
    assert update["sourceMicroversion"] == original["sourceMicroversion"]
    assert update["customMetadata"] == original["customMetadata"]
    rows = {row["parameterId"]: row for row in update["currentConfiguration"]}
    assert rows["root_chord"]["value"] == 92
    assert rows["root_chord"]["expression"] == "92 mm"
    assert rows["sweep_deg"]["value"] == 35
    assert rows["sweep_deg"]["expression"] == "35 deg"
    assert rows["taper_ratio"] == original["currentConfiguration"][1]
    params = {row["parameterId"]: row for row in update["configurationParameters"]}
    assert params["root_chord"]["rangeAndDefault"]["defaultValue"] == 92
    assert params["sweep_deg"]["rangeAndDefault"]["defaultValue"] == 35
    assert params["semi_span"] == original["configurationParameters"][2]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "92"])
def test_rejects_non_finite_or_non_numeric_targets(value):
    with pytest.raises(ValueError, match="numeric|finite"):
        build_configuration_update(configuration(), {"root_chord": value})


@pytest.mark.parametrize("pid,value", [
    ("root_chord", 49), ("root_chord", 131), ("sweep_deg", -0.01), ("sweep_deg", 60.01),
])
def test_rejects_values_outside_inclusive_ranges(pid, value):
    with pytest.raises(ValueError, match="minValue|maxValue"):
        build_configuration_update(configuration(), {pid: value})


def test_rejects_missing_metadata_skew_and_non_quantity_targets():
    config = configuration()
    config["microversionSkew"] = True
    with pytest.raises(ValueError, match="microversionSkew"):
        build_configuration_update(config, {"root_chord": 91})
    config = configuration()
    del config["libraryVersion"]
    with pytest.raises(ValueError, match="libraryVersion"):
        build_configuration_update(config, {"root_chord": 91})
    config = configuration()
    config["libraryVersion"] = True
    with pytest.raises(ValueError, match="integer libraryVersion"):
        build_configuration_update(config, {"root_chord": 91})
    with pytest.raises(ValueError, match="not quantity"):
        build_configuration_update(configuration(), {"edge_profile": "square"})


def test_unsupported_nonempty_units_fail_closed():
    config = configuration()
    config["currentConfiguration"][0]["units"] = "inch"
    with pytest.raises(ValueError, match="unsupported configuration unit"):
        build_configuration_update(config, {"root_chord": 91})


def test_extracts_and_verifies_current_defaults_and_microversion_advance():
    before = configuration()
    after = build_configuration_update(before, {"root_chord": 92, "sweep_deg": 35})
    after["sourceMicroversion"] = "microversion-after"
    # Read-back can serialize numeric values with harmless floating point noise.
    rows = {row["parameterId"]: row for row in after["currentConfiguration"]}
    rows["root_chord"]["value"] = 92.00000000001
    values = configuration_values(after)
    assert values["current"]["root_chord"] == 92.00000000001
    assert values["defaults"]["sweep_deg"] == 35
    assert verify_configuration_update(before, after, {"root_chord": 92, "sweep_deg": 35}) == {
        "ok": True, "missing": [], "mismatched": {},
        "microversion_changed": True, "source_microversion": "microversion-after",
    }


def test_verification_fails_if_current_default_or_microversion_did_not_change():
    before = configuration()
    after = build_configuration_update(before, {"root_chord": 92})
    after["sourceMicroversion"] = before["sourceMicroversion"]
    after["currentConfiguration"][0]["value"] = 91
    result = verify_configuration_update(before, after, {"root_chord": 92})
    assert not result["ok"]
    assert result["microversion_changed"] is False
    assert result["mismatched"]["current:root_chord"]["observed"] == 91


def test_write_url_parser_accepts_only_workspaces():
    workspace = "https://cad.onshape.com/documents/doc/w/work/e/element"
    assert parse_workspace_url(workspace) == ("doc", "work", "element")
    with pytest.raises(ValueError, match="/w/"):
        parse_workspace_url("https://cad.onshape.com/documents/doc/v/version/e/element")
    with pytest.raises(ValueError, match="/w/"):
        parse_workspace_url("https://cad.onshape.com/documents/doc/m/micro/e/element")

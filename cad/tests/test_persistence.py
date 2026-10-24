"""Mocked safety tests for the persistent Onshape handoff primitives.

These tests never construct a real Onshape URL or session.  They exercise the
ledgered HTTP boundary with an in-memory session only.
"""
import json

import pytest

from cad import api as cad_api
from cad.api import commit_to_document
from cad import cache
from cad.ledger import Ledger
from cad.onshape_client import OnshapeClient, build_configuration_update
from shared import fin_geometry
from shared.contracts import CadSource, DesignSpace, ParamSpec


class FakeResponse(object):
    def __init__(self, payload, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession(object):
    """A requests.Session stand-in which records calls without a network."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        assert self.responses, "unexpected mocked request"
        return self.responses.pop(0)


def client(tmp_path, responses):
    ledger = Ledger("mock-persistence", calls_remaining=20, reserve=0,
                    root=str(tmp_path))
    api = OnshapeClient(access_key="test-access", secret_key="test-secret",
                        ledger=ledger, base="https://mock.invalid/api/v10")
    fake = FakeSession(responses)
    api._session = fake
    return api, fake, ledger


def test_update_verify_then_version_are_ledgered_and_use_template_paths(tmp_path):
    """The three explicit calls are ordered update -> read-back -> version."""
    config_body = {
        "currentConfiguration": [{"parameterId": "length", "value": "90 mm"}],
        "serializationVersion": "test",
    }
    observed = {"currentConfiguration": [{"parameterId": "length", "value": "90 mm"}]}
    api, session, ledger = client(tmp_path, [
        FakeResponse(config_body), FakeResponse(observed),
        FakeResponse({"id": "version-result"}),
    ])

    assert api.update_configuration("opaque-did", "opaque-wid", "opaque-eid", config_body) == config_body
    assert api.verify_configuration("opaque-did", "opaque-wid", "opaque-eid",
                                    {"length": "90 mm"}) == {
        "ok": True, "missing": [], "mismatched": {},
    }
    assert api.create_version("opaque-did", "opaque-wid", "Champion handoff") == {
        "id": "version-result"
    }

    assert [call["method"] for call in session.calls] == ["POST", "GET", "POST"]
    assert session.calls[0]["json"] == config_body
    assert session.calls[2]["json"] == {
        "documentId": "opaque-did", "workspaceId": "opaque-wid",
        "name": "Champion handoff",
    }
    assert ledger.calls_total() == 3
    with open(ledger.path) as fh:
        entries = [json.loads(line) for line in fh]
    paths = [entry["path"] for entry in entries if entry["kind"] == "call"]
    assert paths == [
        "/elements/d/{did}/w/{wid}/e/{eid}/configuration",
        "/elements/d/{did}/w/{wid}/e/{eid}/configuration",
        "/documents/d/{did}/versions",
    ]
    ledger_text = open(ledger.path).read()
    for value in ("opaque-did", "opaque-wid", "opaque-eid", "test-access", "test-secret"):
        assert value not in ledger_text


def test_verification_reports_missing_or_changed_values(tmp_path):
    api, _session, ledger = client(tmp_path, [FakeResponse({
        "currentConfiguration": [{"parameterId": "length", "value": "80 mm"}],
    })])

    got = api.verify_configuration("document", "workspace", "element", {
        "length": "90 mm", "profile": "square",
    })

    assert got == {
        "ok": False,
        "missing": ["profile"],
        "mismatched": {"length": {"expected": "90 mm", "observed": "80 mm"}},
    }
    assert ledger.calls_total() == 1


def test_malformed_readback_never_verifies(tmp_path):
    api, _session, ledger = client(tmp_path, [FakeResponse({"currentConfiguration": [{}]})])

    with pytest.raises(ValueError, match="parameterId/value"):
        api.verify_configuration("document", "workspace", "element", {"length": "90 mm"})
    assert ledger.calls_total() == 1, "the attempted GET is accounted before parsing"


def space():
    return DesignSpace(
        id="persist-test", name="Persistence test", scorer="fin_v1",
        parameters=[ParamSpec(name="root_chord", kind="continuous", unit="mm",
                              min=50.0, max=130.0, step=1.0, default=90.0)],
        source=CadSource(kind="onshape", mode="configuration",
                         doc_url="https://cad.onshape.com/documents/doc/w/work/e/element"),
    )


def test_commit_requires_explicit_opt_in_and_never_claims_success(monkeypatch):
    monkeypatch.delenv("DARWIN_ONSHAPE_WRITE", raising=False)
    monkeypatch.delenv("DARWIN_ONSHAPE_WRITE_ISOLATED", raising=False)

    ref = commit_to_document(space(), {"root_chord": 90.0})

    assert ref.status == "skipped"
    assert ref.source == "none"
    assert ref.regen_status == "NOT_ATTEMPTED"
    assert ref.error == "onshape_write_disabled"
    assert ref.onshape_calls == 0


def test_commit_requires_an_exact_acknowledged_workspace(monkeypatch):
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE", "1")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_ISOLATED", "1")
    monkeypatch.delenv("DARWIN_ONSHAPE_WRITE_TARGET_URL", raising=False)

    ref = commit_to_document(space(), {"root_chord": 90.0})

    assert ref.status == "skipped"
    assert ref.source == "none"
    assert ref.regen_status == "NOT_ATTEMPTED"
    assert ref.error == "onshape_write_target_not_acknowledged"
    assert ref.onshape_calls == 0


def fin_space(include_edge_profile=False):
    specs = [
        ParamSpec(name="root_chord", kind="continuous", unit="mm", min=50,
                  max=130, step=0.5, default=90.0),
        ParamSpec(name="taper_ratio", kind="continuous", min=0.2,
                  max=1.0, step=0.01, default=0.5),
        ParamSpec(name="semi_span", kind="continuous", unit="mm", min=30,
                  max=90, step=0.5, default=60.0),
        ParamSpec(name="sweep_deg", kind="continuous", unit="deg", min=0,
                  max=60, step=0.5, default=30.0),
        ParamSpec(name="thickness", kind="continuous", unit="mm", min=2,
                  max=5, step=0.1, default=3.0),
        ParamSpec(name="edge_profile", kind="choice", choices=["square"],
                  default="square", cad_driven=include_edge_profile),
    ]
    return DesignSpace(
        id="fin-persist-test", name="Fin persistence test", scorer="fin_v1",
        parameters=specs,
        source=CadSource(kind="onshape", mode="configuration",
                         doc_url="https://cad.onshape.com/documents/doc/w/work/e/element"),
    )


def config_snapshot(source_microversion="before"):
    values = {
        "root_chord": (90.0, 50.0, 130.0, "LENGTH", "millimeter", "90 mm"),
        "taper_ratio": (0.5, 0.2, 1.0, "REAL", "", "0.5"),
        "semi_span": (60.0, 30.0, 90.0, "LENGTH", "millimeter", "60 mm"),
        "sweep_deg": (30.0, 0.0, 60.0, "ANGLE", "degree", "30 deg"),
        "thickness": (3.0, 2.0, 5.0, "LENGTH", "millimeter", "3 mm"),
    }
    return {
        "btType": "BTConfigurationResponse-2019",
        "serializationVersion": "1.2.7", "libraryVersion": 2522,
        "sourceMicroversion": source_microversion, "microversionSkew": False,
        "rejectMicroversionSkew": False,
        "configurationParameters": [
            {
                "btType": "BTMConfigurationParameterQuantity-1826",
                "parameterId": name, "parameterName": name,
                "quantityType": row[3],
                "rangeAndDefault": {
                    "btType": "BTQuantityRange-181", "defaultValue": row[0],
                    "minValue": row[1], "maxValue": row[2], "units": row[4],
                },
            }
            for name, row in values.items()
        ],
        "currentConfiguration": [
            {
                "btType": "BTMParameterQuantity-147", "parameterId": name,
                "value": row[0], "expression": row[5], "units": row[4],
            }
            for name, row in values.items()
        ],
    }


def champion_params():
    return {
        "root_chord": 92.0, "taper_ratio": 0.55, "semi_span": 62.0,
        "sweep_deg": 32.0, "thickness": 3.2, "edge_profile": "square",
    }


def enable_write(monkeypatch):
    target = "https://cad.onshape.com/documents/doc/w/work/e/element"
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE", "1")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_ISOLATED", "1")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_TARGET_URL", target)


def test_commit_sequence_verifies_values_geometry_then_versions(monkeypatch, tmp_path):
    enable_write(monkeypatch)
    params = champion_params()
    before = config_snapshot()
    expected = {key: value for key, value in params.items() if key != "edge_profile"}
    after = build_configuration_update(before, expected)
    after["btType"] = "BTConfigurationResponse-2019"
    after["sourceMicroversion"] = "after"
    stl_text = fin_geometry.prism_stl(params)
    api, session, ledger = client(tmp_path, [
        FakeResponse(before), FakeResponse(after), FakeResponse(after),
        FakeResponse({}, text=stl_text), FakeResponse({"id": "version-id"}),
    ])
    monkeypatch.setattr(cad_api, "_ledger", ledger)
    monkeypatch.setattr(cad_api, "_client", api)
    monkeypatch.setattr(cache, "store", lambda ref, text: ref)

    ref = commit_to_document(fin_space(), params)

    assert ref.status == "ready"
    assert ref.regen_status == "OK"
    assert ref.onshape_calls == 5
    assert [call["method"] for call in session.calls] == ["GET", "POST", "GET", "GET", "POST"]
    assert session.calls[1]["json"]["btType"] == "BTConfigurationUpdateCall-2933"
    assert session.calls[-1]["json"]["name"].startswith("Darwin verified ")


def test_commit_stops_before_post_when_cad_parameter_is_missing(monkeypatch, tmp_path):
    enable_write(monkeypatch)
    api, session, ledger = client(tmp_path, [FakeResponse(config_snapshot())])
    monkeypatch.setattr(cad_api, "_ledger", ledger)
    monkeypatch.setattr(cad_api, "_client", api)

    ref = commit_to_document(fin_space(include_edge_profile=True), champion_params())

    assert ref.status == "failed"
    assert ref.regen_status == "NOT_ATTEMPTED"
    assert "edge_profile" in ref.error
    assert [call["method"] for call in session.calls] == ["GET"]

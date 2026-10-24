"""Mocked safety tests for the persistent Onshape handoff primitives.

These tests never construct a real Onshape URL or session.  They exercise the
ledgered HTTP boundary with an in-memory session only.
"""
import json

import pytest

from cad.api import commit_to_document
from cad.ledger import Ledger
from cad.onshape_client import OnshapeClient
from shared.contracts import CadSource, DesignSpace, ParamSpec


class FakeResponse(object):
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

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
        source=CadSource(kind="onshape", mode="configuration"),
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


def test_commit_refuses_an_unverified_write_schema_even_after_opt_in(monkeypatch):
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE", "1")
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_ISOLATED", "1")

    ref = commit_to_document(space(), {"root_chord": 90.0})

    assert ref.status == "skipped"
    assert ref.source == "none"
    assert ref.regen_status == "NOT_ATTEMPTED"
    assert "schema_unverified" in ref.error
    assert ref.onshape_calls == 0

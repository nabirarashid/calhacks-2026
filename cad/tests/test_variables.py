"""A3: Variable-feature writes (the live morph), fully mocked. Format matches a real Onshape
response captured Sat 15:44 on the disposable copy (see cad/SPIKE.md)."""
import copy
import json
from pathlib import Path

import pytest

from cad import variables

FIX = json.loads((Path(__file__).parent / "fixtures" / "features_wing.json").read_text())
URL = "https://cad.onshape.com/documents/d0c/w/w0r/e/e1e"
UNITS = {"aoa_deg": "deg", "span_mm": "mm", "chord_mm": "mm", "flap_angle_deg": "deg", "flap_chord_frac": "",
         "endplate_height_mm": "mm"}
BOX = "solid b\n" + "".join("facet normal 0 0 0\nouter loop\nvertex %s\nvertex %s\nvertex %s\nendloop\nendfacet\n" % t
                            for t in [("0 0 0", "1 0 0", "0 1 0"), ("0 0 0", "0 1 0", "0 0 1"),
                                      ("0 0 0", "0 0 1", "1 0 0"), ("1 0 0", "0 0 1", "0 1 0")]) + "endsolid b\n"


class FakeLedger:
    def __init__(self, stop=False):
        self.n, self.stop = 0, stop

    def hard_stop(self):
        return self.stop

    def calls_logged(self):
        return self.n


class FakeClient:
    def __init__(self, ledger, regen="OK", lose_write=False):
        self.features = copy.deepcopy(FIX)
        self.ledger, self.regen, self.lose_write = ledger, regen, lose_write
        self.posts, self.versions = [], []

    def get_features(self, did, wid, eid, purpose=""):
        self.ledger.n += 1
        return copy.deepcopy(self.features)

    def request(self, method, path, purpose, **kw):
        self.ledger.n += 1
        if path.endswith("/elements"):
            return Resp([{"id": "e1e", "name": "Part Studio 1"}])
        feature = kw["json_body"]["feature"]
        self.posts.append(feature)
        if not self.lose_write:
            self.features["features"] = [feature if f["featureId"] == feature["featureId"] else f
                                         for f in self.features["features"]]
        return Resp({"featureState": {"featureStatus": self.regen}, "sourceMicroversion": "mv%d" % len(self.posts)})

    def export_stl(self, did, wid, eid, purpose=""):
        self.ledger.n += 1
        return BOX

    def create_version(self, did, wid, name, purpose=""):
        self.ledger.n += 1
        self.versions.append(name)
        return {"id": "ver%d" % len(self.versions)}


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


@pytest.fixture
def cad(monkeypatch, tmp_path):
    from cad import api, cache
    monkeypatch.chdir(tmp_path)                        # cache.store writes .darwin/geometry relative to cwd
    monkeypatch.setenv("DARWIN_DOC_WING", URL)
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_FIN,DARWIN_DOC_WING")
    led = FakeLedger()
    client = FakeClient(led)
    monkeypatch.setattr(api, "_get_ledger", lambda: led)
    monkeypatch.setattr(api, "_get_client", lambda: client)
    return client


def _expr(client, name):
    return variables.parse_variables(client.features)[name]["expression"]


def test_parse_real_format():
    v = variables.parse_variables(FIX)
    assert set(v) == set(UNITS)
    assert (v["aoa_deg"]["type"], v["aoa_deg"]["value_param"], v["aoa_deg"]["value"], v["aoa_deg"]["unit"]) == \
        ("ANGLE", "angleValue", 6.0, "deg")
    assert (v["flap_chord_frac"]["type"], v["flap_chord_frac"]["unit"]) == ("NUMBER", "")
    assert variables.parse_literal("#a * 2") == (None, "")


def test_apply_writes_only_changed_variables_and_verifies(cad):
    ref = variables.apply_values(URL, {"aoa_deg": 8.0, "span_mm": 950.0, "flap_chord_frac": 0.35,
                                       "chord_mm": 280.0}, UNITS)
    assert ref.status == "ready" and ref.regen_status == "OK" and ref.source == "onshape_feature"
    assert len(cad.posts) == 3                                    # chord unchanged: not written
    assert (_expr(cad, "aoa_deg"), _expr(cad, "span_mm"), _expr(cad, "flap_chord_frac")) == ("8 deg", "950 mm", "0.35")
    assert ref.onshape_calls == 1 + 3 + 1 + 1                     # read, 3 writes, read-back, STL
    assert ref.bbox_mm and Path(".darwin/geometry/%s.stl" % ref.geometry_key).exists()
    assert ref.geometry_key.isalnum()


def test_unchanged_values_cost_only_the_read_and_stl(cad):
    ref = variables.apply_values(URL, {"aoa_deg": 6.0}, UNITS)
    assert ref.status == "ready" and cad.posts == [] and ref.onshape_calls == 2


def test_refusals_never_touch_onshape(cad, monkeypatch):
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_FIN")
    ref = variables.apply_values(URL, {"aoa_deg": 8.0}, UNITS)
    assert ref.status == "skipped" and "write_not_allowed" in ref.error and cad.ledger.n == 0
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_WING")
    cad.ledger.stop = True
    ref = variables.apply_values(URL, {"aoa_deg": 8.0}, UNITS)
    assert ref.status == "skipped" and ref.error == "onshape_budget_reserve" and cad.ledger.n == 0
    assert variables.create_version(URL, "x") is None


def test_missing_variable_writes_nothing(cad):
    ref = variables.apply_values(URL, {"aoa_deg": 8.0, "gurney_mm": 5.0}, UNITS)
    assert ref.status == "failed" and "gurney_mm" in ref.error and cad.posts == []


def test_failed_regeneration_is_reverted(cad):
    cad.regen = "ERROR"
    ref = variables.apply_values(URL, {"aoa_deg": 30.0}, UNITS)
    assert ref.status == "failed" and "reverted" in ref.error
    assert len(cad.posts) == 2 and cad.posts[1]["parameters"][2]["expression"] == "6 deg"   # original restored


def test_read_back_mismatch_fails(cad):
    cad.lose_write = True
    ref = variables.apply_values(URL, {"span_mm": 990.0}, UNITS)
    assert ref.status == "failed" and "read-back" in ref.error


def test_versions_and_element_lookup(cad):
    assert variables.create_version(URL, "Before Darwin") == "ver1" and cad.versions == ["Before Darwin"]
    assert variables.resolve_doc("https://cad.onshape.com/documents/d0c/w/w0r", cad) == ("d0c", "w0r", "e1e")
    assert variables.format_expression(8, "deg") == "8 deg" and variables.format_expression(0.3, "") == "0.3"

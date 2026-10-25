"""A3: Variable-feature writes (the live morph), fully mocked. Format matches a real Onshape
response captured Sat 15:44 on the disposable copy (see cad/SPIKE.md)."""
import copy
import json
from pathlib import Path

import pytest

from cad import variables

FIX = json.loads((Path(__file__).parent / "fixtures" / "features_wing.json").read_text())
NESTED_FIX = json.loads((Path(__file__).parent / "fixtures" / "features_wing_nested.json").read_text())
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
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path / ".darwin"))   # no adopted ids from other tests
    monkeypatch.setenv("DARWIN_DOC_WING", URL)
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_FIN,DARWIN_DOC_WING")
    led = FakeLedger()
    client = FakeClient(led)
    monkeypatch.setattr(api, "_get_ledger", lambda: led)
    monkeypatch.setattr(api, "_get_client", lambda: client)
    monkeypatch.setattr(variables, "_stl_refused", False)
    monkeypatch.setattr(variables, "RATE_LIMIT_WAITS_S", (0.0, 0.0))
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


def test_parse_nested_feature_and_parameter_wrappers():
    parsed = variables.parse_variables(NESTED_FIX)
    assert set(parsed) == {"aoa_deg", "span_mm"}
    assert parsed["aoa_deg"]["feature_id"] == "fixture-aoa-feature"
    assert parsed["aoa_deg"]["expression"] == "6 deg"
    assert parsed["span_mm"]["value"] == 850.0


@pytest.mark.parametrize("name,value,unit,variable_type,parameter_id,expression", [
    ("span_mm", 850, "mm", "LENGTH", "lengthValue", "850 mm"),
    ("aoa_deg", 6, "deg", "ANGLE", "angleValue", "6 deg"),
    ("flap_chord_frac", 0.3, "", "NUMBER", "numberValue", "0.3"),
])
def test_build_variable_feature_uses_post_schema(
        name, value, unit, variable_type, parameter_id, expression):
    payload = variables.build_variable_feature(name, value, unit)
    assert payload["btType"] == "BTFeatureDefinitionCall-1406"
    feature = payload["feature"]
    params = {row["parameterId"]: row for row in feature["parameters"]}
    assert params["name"]["value"] == name
    assert params["variableType"]["value"] == variable_type
    assert params[parameter_id]["expression"] == expression
    assert params[parameter_id]["isInteger"] is False
    assert all("message" not in row for row in feature["parameters"])


@pytest.mark.parametrize("name,value,unit", [
    ("bad name", 1, "mm"), ("9bad", 1, "mm"),
    ("span_mm", float("nan"), "mm"), ("span_mm", True, "mm"),
    ("span_mm", 1, "cm"),
])
def test_build_variable_feature_rejects_unsafe_inputs(name, value, unit):
    with pytest.raises(ValueError):
        variables.build_variable_feature(name, value, unit)


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


def test_ensure_variables_creates_only_missing_ones_at_the_top(cad, monkeypatch):
    rolls = []
    real_request = cad.request

    def request(method, path, purpose, **kw):
        if path.endswith("/rollback"):
            cad.ledger.n += 1
            rolls.append(kw["json_body"]["rollbackIndex"])
            return Resp({"rollbackIndex": kw["json_body"]["rollbackIndex"]})
        if path.endswith("/features"):
            cad.ledger.n += 1
            cad.features["features"].insert(len(rolls) and 0, kw["json_body"]["feature"])
            return Resp({"featureState": {"featureStatus": "OK"}, "sourceMicroversion": "mvx"})
        return real_request(method, path, purpose, **kw)

    monkeypatch.setattr(cad, "request", request)
    made = variables.ensure_variables(URL, [("aoa_deg", "deg", 6), ("gurney_mm", "mm", 5), ("gap_frac", "", 0.02)])
    assert made == ["gurney_mm", "gap_frac"] and rolls == [0, -1]
    v = variables.parse_variables(cad.features)
    assert v["gurney_mm"]["expression"] == "5 mm" and v["gurney_mm"]["type"] == "LENGTH"
    assert v["gap_frac"]["expression"] == "0.02" and v["gap_frac"]["type"] == "NUMBER"
    assert variables.ensure_variables(URL, [("aoa_deg", "deg", 6)]) == []


def test_rate_limit_is_retried(cad, monkeypatch):
    from cad.onshape_client import OnshapeError
    real, hits = cad.get_features, []

    def flaky(*a, **k):
        hits.append(1)
        if len(hits) == 1:
            raise OnshapeError("GET features -> HTTP 429", 429)
        return real(*a, **k)
    monkeypatch.setattr(cad, "get_features", flaky)
    assert variables.apply_values(URL, {"aoa_deg": 8.0}, UNITS).status == "ready" and _expr(cad, "aoa_deg") == "8 deg"


def test_stl_401_keeps_the_write_and_stops_retrying_the_export(cad, monkeypatch):
    from cad.onshape_client import OnshapeError
    exports = []

    def refused(*a, **k):
        exports.append(1)
        raise OnshapeError("GET stl -> HTTP 401", 401)
    monkeypatch.setattr(cad, "export_stl", refused)
    first = variables.apply_values(URL, {"aoa_deg": 8.0}, UNITS)
    second = variables.apply_values(URL, {"aoa_deg": 9.0}, UNITS)
    assert first.status == second.status == "ready" and "stl_export" in second.error
    assert len(exports) == 1 and _expr(cad, "aoa_deg") == "9 deg"


class AdoptedClient:
    """Feature writes, Variables API and bounding boxes only; GET /features always fails (its quota is gone)."""

    def __init__(self, ledger, regen="OK"):
        self.ledger, self.regen = ledger, regen
        self.vars = {"aoa_deg": "6 deg", "span_mm": "850 mm", "flap_chord_frac": "0.3"}
        self.posts = []

    def get_features(self, *a, **k):
        from cad.onshape_client import OnshapeError
        raise OnshapeError("GET features -> HTTP 429", 429)

    def request(self, method, path, purpose, **kw):
        self.ledger.n += 1
        if path.endswith("/variables"):
            return Resp([{"variables": [{"name": n, "expression": e, "type": "X"} for n, e in self.vars.items()]}])
        if path.endswith("/currentmicroversion"):
            return Resp({"microversion": "mv0"})
        if path.endswith("/boundingboxes"):
            return Resp({"lowX": 0, "lowY": 0, "lowZ": 0, "highX": 0.28, "highY": 0.85, "highZ": 0.05})
        if path.endswith("/rollback"):
            return Resp({"rollbackIndex": kw["json_body"]["rollbackIndex"]})
        feature = kw["json_body"]["feature"]
        self.posts.append((path, feature))
        if self.regen == "OK":
            p = {q["parameterId"]: q for q in feature["parameters"]}
            self.vars[p["name"]["value"]] = next(q["expression"] for q in feature["parameters"] if "expression" in q)
        return Resp({"featureState": {"featureStatus": self.regen}, "sourceMicroversion": "mv1",
                     "feature": dict(feature, featureId=feature.get("featureId") or "Fnew%d" % len(self.posts))})


@pytest.fixture
def adopted(monkeypatch, tmp_path):
    from cad import api
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DARWIN_DOC_WING", URL)
    monkeypatch.setenv("DARWIN_ONSHAPE_WRITE_DOCS", "DARWIN_DOC_WING")
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path / ".darwin"))
    led = FakeLedger()
    client = AdoptedClient(led)
    monkeypatch.setattr(api, "_get_ledger", lambda: led)
    monkeypatch.setattr(api, "_get_client", lambda: client)
    monkeypatch.setattr(variables, "RATE_LIMIT_WAITS_S", (0.0, 0.0))
    return client


def test_adopt_then_write_by_id_without_reading_the_feature_list(adopted):
    ids = variables.adopt_variables(URL, [("aoa_deg", "deg", 6.0), ("span_mm", "mm", 850.0)], after_index=6)
    assert set(ids) == {"aoa_deg", "span_mm"}
    assert [p for p, _ in adopted.posts[:1]][0].endswith("/features")                      # created, ids kept
    assert all(f["name"].startswith("Darwin: ") for _, f in adopted.posts)
    adopted.posts.clear()
    ref = variables.apply_values(URL, {"aoa_deg": 9.0, "span_mm": 850.0}, {"aoa_deg": "deg", "span_mm": "mm"})
    assert ref.status == "ready" and ref.regen_status == "OK" and ref.bbox_mm == [0, 0, 0, 280.0, 850.0, 50.0]
    assert len(adopted.posts) == 1 and adopted.posts[0][0].endswith("/featureid/" + ids["aoa_deg"])   # span unchanged
    assert adopted.vars["aoa_deg"] == "9 deg" and variables.list_variables(URL)["aoa_deg"]["value"] == 9.0


def test_adopted_regen_failure_reverts(adopted):
    variables.adopt_variables(URL, [("aoa_deg", "deg", 6.0)], after_index=6)
    adopted.regen = "ERROR"
    ref = variables.apply_values(URL, {"aoa_deg": 40.0}, {"aoa_deg": "deg"})
    assert ref.status == "failed" and "reverted" in ref.error and len(adopted.posts) == 3      # add, write, revert

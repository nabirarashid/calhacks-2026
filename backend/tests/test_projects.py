import shutil
from pathlib import Path

import pytest

from shared.contracts import GeometryRef
from shared.manifest import CheckResult, GeometryEvidence, ManifestUpdate, ProbeResult
from shared.mocks import fake_structural
from shared.mocks import make_fixtures_v2 as fx

from backend.projects import ActivationEvidence, ProjectRegistry, compute_maturity

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def reg(tmp_path):
    shutil.copytree(ROOT / "projects", tmp_path / "projects")
    return ProjectRegistry(root=tmp_path / "projects", runtime=tmp_path / "runtime", env=lambda: {})


def _probe(ok=True):
    ref = GeometryRef(geometry_key="k", status="ready" if ok else "failed", source="mock")
    ev = GeometryEvidence(geometry_key="k", parse_ok=ok, watertight=ok, checks=[CheckResult(id="parse", passed=ok)])
    return ProbeResult(case="seed", params={}, geometry=ref, evidence=ev)


def _full(m):
    return ActivationEvidence(adapter_findings=fake_structural.validate_manifest(m), probes=[_probe()],
                              baseline_reproduced=True, golden_tests=["sim/tests/test_structural_golden.py"])


def test_committed_projects_load_at_level_3(reg):
    assert reg.ids() == ["fin_reference", "rear_wing"]
    by_id = {s.project_id: s for s in reg.summaries()}
    assert (by_id["fin_reference"].maturity, by_id["fin_reference"].domain_pack) == (3, "rocket_fin")
    assert (by_id["rear_wing"].maturity, by_id["rear_wing"].domain_pack) == (3, "aero")


def test_rules_climb_one_level_at_a_time():
    draft = fx.manifest_bracket(1)
    assert compute_maturity(draft, env={})[0] == 1
    reviewed = draft.model_copy(update={
        "semantics": [s.model_copy(update={"confirmed": True}) for s in draft.semantics],
        "protected": fx.bracket_protected()})
    lvl, _, blocked = compute_maturity(reviewed, env={})
    assert lvl == 2 and any("adapters not consulted" in b for b in blocked)
    full = fx.manifest_bracket(3)
    assert compute_maturity(full, ActivationEvidence(), env={})[0] == 2        # no evidence, no level 3
    lvl, got, blocked = compute_maturity(full, _full(full), env={})
    assert lvl == 3 and any("no recorded live smoke write" in b for b in blocked)
    env = {"DARWIN_DOC_BRACKET_WRITE": "https://cad.onshape.com/documents/d/w/w1/e/e", "DARWIN_ONSHAPE_WRITE_ISOLATED": "1"}
    ev = _full(full).model_copy(update={"live_write": "cad/SPIKE.md#live-write"})
    assert compute_maturity(full, ev, env=env)[0] == 4


def test_failed_probe_or_unconfirmed_load_blocks_level_3():
    full = fx.manifest_bracket(3)
    bad = _full(full).model_copy(update={"probes": [_probe(ok=False)]})
    assert compute_maturity(full, bad, env={})[0] == 2
    lc = full.load_cases[0].model_copy(update={"confirmed": False})
    m = full.model_copy(update={"load_cases": [lc]})
    assert compute_maturity(m, _full(m), env={})[0] == 2


def test_update_writes_an_immutable_revision_and_never_raises_the_level(reg, tmp_path):
    draft = fx.manifest_bracket(1).model_copy(update={"project_id": "bracket_x"})
    reg.create(draft)
    sem = [s.model_copy(update={"confirmed": True, "confidence": None}) for s in draft.semantics]
    m2 = reg.update("bracket_x", ManifestUpdate(revision=1, by="hzw", semantics=sem, protected=fx.bracket_protected()))
    assert m2.revision == 2 and m2.authority.maturity == 1                   # rules say 2, edits can't raise
    assert (tmp_path / "runtime" / "bracket_x" / "r1.json").exists()
    assert (tmp_path / "runtime" / "bracket_x" / "r2.json").exists()
    with pytest.raises(ValueError):
        reg.update("bracket_x", ManifestUpdate(revision=1, by="hzw"))      # stale
    m3, blocked = reg.activate("bracket_x", ActivationEvidence())
    assert m3.authority.maturity == 2 and m3.revision == 3


def test_answers_are_confirmed_by_the_engineer_and_close_questions(reg):
    full = fx.manifest_bracket(3)
    draft = fx.manifest_bracket(1).model_copy(update={
        "project_id": "bracket_y", "load_cases": [full.load_cases[0].model_copy(update={"confirmed": False,
                                                                                         "vector_n": None})]})
    reg.create(draft)
    mat = full.material.model_dump(mode="json")
    mat.pop("source")
    mat["confirmed"] = False
    m2 = reg.update("bracket_y", ManifestUpdate(revision=1, by="hzw", answers={
        "material": mat, "load_cases[0].vector_n": [0.0, -20.0, 0.0]}))
    assert m2.material.confirmed and m2.material.source.source_id == "engineer:hzw"
    assert m2.load_cases[0].confirmed and m2.load_cases[0].vector_n == [0.0, -20.0, 0.0]
    assert {q.field for q in m2.open_questions} == {"load_cases[0].fixtures"}


def test_urls_never_reach_disk(reg):
    m = fx.manifest_bracket(1).model_copy(update={"project_id": "leaky"})
    m = m.model_copy(update={"cad": m.cad.model_copy(update={"doc_ref": "https://cad.onshape.com/documents/x"})})
    with pytest.raises(ValueError):
        reg.create(m)

"""P1-9: the core imports nothing domain-specific, and a non-fin project runs through the
unchanged run loop."""
import ast
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = ("shared.fin_geometry", "sim.plugins.fin_v1", "domains.rocket_fin")
# Known, tracked exceptions. Each must name the plan item that removes it.
ALLOWED = {
    "cad/stl.py": "W-A P1-A1 moves the fin bbox/volume check into domains/rocket_fin/verifier.py",
    "cad/spike.py": "Fri configuration spike script; not imported by the running system",
}


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            for a in node.names:
                yield "%s.%s" % (node.module, a.name)


def test_core_imports_no_domain_code():
    bad = []
    for folder in ("backend", "cad"):
        for path in (ROOT / folder).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if "/tests/" in rel or rel in ALLOWED:
                continue
            bad += ["%s imports %s" % (rel, name) for name in _imports(path)
                    if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)]
    assert bad == []


def test_allowlist_entries_still_exist():
    assert all((ROOT / rel).exists() for rel in ALLOWED), "remove allowlist entries for deleted files"


@pytest.fixture
def bracket_env(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    shutil.copytree(ROOT / "projects", projects)
    (projects / "bracket").mkdir()
    shutil.copy(ROOT / "shared" / "fixtures" / "v2" / "manifest_bracket.json", projects / "bracket" / "r3.json")
    monkeypatch.setenv("DARWIN_PROJECTS_DIR", str(projects))
    monkeypatch.setenv("DARWIN_SIM", "real")
    monkeypatch.setenv("DARWIN_CAD", "off")
    monkeypatch.setenv("DARWIN_LLM_PROVIDER", "mock")
    monkeypatch.setenv("FAKE_LLM_LATENCY", "0")
    monkeypatch.setenv("DARWIN_CACHE_DIR", str(tmp_path / ".darwin"))
    yield


def test_bracket_runs_through_the_unchanged_run_loop(bracket_env):
    from shared.contracts import RunConfig
    from shared.mocks.make_fixtures_v2 import BRACKET_GOAL
    from backend.bus import Bus
    from backend.run_loop import RunController, new_run_id
    from backend.wiring import Wiring

    w = Wiring()
    space = w.resolve("bracket")
    assert space.scorer == "structural_analytic_v1:bracket"
    ctl = RunController(w, Bus().open(new_run_id(), record=False), space, BRACKET_GOAL,
                        RunConfig(population=6, generations=3, profile="bench"))
    ctl.start()
    ctl.thread.join(120)
    assert not ctl.thread.is_alive()
    summary = ctl.ch.events[-1]["payload"]["summary"]
    assert summary["status"] == "complete"
    champ = summary["champion"]
    assert set(champ["score"]["metrics"]) >= {"mass_g", "safety_factor", "stress_hole_mpa"}
    assert "drag_n" not in champ["score"]["metrics"]
    assert set(summary["baseline_best"]) == {"cmaes", "random"}


def test_bracket_prompts_carry_no_rocket_wording(bracket_env):
    from backend.agents.base import system_prompt
    from backend.wiring import Wiring
    w = Wiring()
    for role in ("goal_parser", "proposer", "critic", "strategist", "reporter"):
        text = system_prompt(role, w.resolve("bracket")).lower()
        assert "rocket" not in text and "fin" not in text.split()
    assert "rocket" in system_prompt("proposer", w.resolve("fin_reference")).lower()

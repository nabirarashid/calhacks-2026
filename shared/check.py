"""Validate every shared fixture against the frozen models. Run: python -m shared.check (or `make contracts`)."""
import json
import re
import sys
from pathlib import Path
from typing import List

from shared.contracts import (
    CONTRACT_VERSION, BudgetStatus, DesignResult, DesignSpace, Goal, MetricInfo, Preset, Score, canonicalize,
    param_hash,
)
from shared.events import Event, validate_event
from shared.manifest import (
    PERMITTED_BY_LEVEL, CadInventory, CapabilityReport, ProjectManifest, manifest_hash,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

SINGLE = {
    "design_space_fin.json": DesignSpace,
    "goal_example.json": Goal,
    "score_example.json": Score,
    "design_result_example.json": DesignResult,
    "budget_example.json": BudgetStatus,
}


def check_recording(path: Path) -> List[str]:
    """Structural checks for a run recording (.jsonl). Returns a list of problems."""
    problems = []  # type: List[str]
    events = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = Event.model_validate_json(line)
            validate_event(ev)
            events.append(ev)
        except Exception as e:  # noqa: BLE001 — report every bad line
            problems.append("%s:%d: %s" % (path.name, i, str(e).splitlines()[0]))
    if not events:
        return problems + ["%s: no events" % path.name]
    if events[0].type != "run_started":
        problems.append("%s: first event is %s, expected run_started" % (path.name, events[0].type))
    if events[-1].type != "run_complete":
        problems.append("%s: last event is %s, expected run_complete" % (path.name, events[-1].type))
    seqs = [e.seq for e in events]
    if any(b <= a for a, b in zip(seqs, seqs[1:])):
        problems.append("%s: seq is not strictly increasing" % path.name)
    if len({e.run_id for e in events}) != 1:
        problems.append("%s: more than one run_id" % path.name)
    return problems


V2 = FIXTURES / "v2"
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def check_manifest(name: str, m: ProjectManifest) -> List[str]:
    """Rules from PLAN.md v3 B.3/B.5/B.6 that the type system alone can't express."""
    out = []  # type: List[str]
    for ref in (m.cad.doc_ref, m.cad.write_target_ref):
        if ref is not None and not ENV_NAME.match(ref):
            out.append("%s: cad refs must be env var NAMES, got %r" % (name, ref))
    if m.design_space.source.doc_url:
        out.append("%s: design_space.source.doc_url must be null" % name)
    params = {p.name for p in m.design_space.parameters}
    if {s.name for s in m.semantics} != params:
        out.append("%s: semantics must cover exactly the design_space parameters" % name)
    if not set(m.authority.permitted) <= set(PERMITTED_BY_LEVEL[m.authority.maturity]):
        out.append("%s: permitted actions exceed maturity %d" % (name, m.authority.maturity))
    ids = {p.id for p in m.protected}
    for lc in m.load_cases:
        for ref in ([lc.applied_at] if lc.applied_at else []) + lc.fixtures:
            if ref not in ids:
                out.append("%s: load case %s references unknown interface %s" % (name, lc.id, ref))
    if m.authority.maturity >= 2 and not all(s.confirmed for s in m.semantics):
        out.append("%s: maturity >= 2 requires every semantics entry confirmed" % name)
    if m.authority.maturity >= 3:
        if m.domain_pack is None or m.analysis is None:
            out.append("%s: maturity >= 3 requires a domain pack and an analysis plan" % name)
        if m.material is not None and not m.material.confirmed:
            out.append("%s: maturity >= 3 with an unconfirmed material" % name)
        if any(not lc.confirmed for lc in m.load_cases):
            out.append("%s: maturity >= 3 with an unconfirmed load case" % name)
        if any(q.required_for <= 3 for q in m.open_questions):
            out.append("%s: maturity >= 3 with open blocking questions" % name)
    manifest_hash(m)
    return out


def check_v2() -> List[str]:
    problems = []  # type: List[str]
    models = {"manifest_": ProjectManifest, "inventory_": CadInventory, "capability_": CapabilityReport}
    for path in sorted(V2.glob("*.json")):
        model = next((mdl for prefix, mdl in models.items() if path.name.startswith(prefix)), None)
        try:
            if model is ProjectManifest:
                problems += check_manifest(path.name, ProjectManifest.model_validate_json(path.read_text()))
            elif model is not None:
                model.model_validate_json(path.read_text())
            elif path.name.startswith("metric_catalog_"):
                [MetricInfo.model_validate(m) for m in json.loads(path.read_text())]
            elif path.name.startswith("goal_"):
                Goal.model_validate_json(path.read_text())
            else:
                problems.append("%s: no model registered for this fixture" % path.name)
        except Exception as e:  # noqa: BLE001
            problems.append("%s: %s" % (path.name, str(e).splitlines()[0]))
    for rec in sorted(V2.glob("*.jsonl")):
        problems += check_recording(rec)
    return problems


def main() -> int:
    problems = []  # type: List[str]
    for name, model in SINGLE.items():
        try:
            model.model_validate_json((FIXTURES / name).read_text())
        except Exception as e:  # noqa: BLE001
            problems.append("%s: %s" % (name, e))
    try:
        [MetricInfo.model_validate(m) for m in json.loads((FIXTURES / "metric_catalog_fin.json").read_text())]
    except Exception as e:  # noqa: BLE001
        problems.append("metric_catalog_fin.json: %s" % e)
    try:
        [Preset.model_validate(m) for m in json.loads((FIXTURES / "presets.json").read_text())]
    except Exception as e:  # noqa: BLE001
        problems.append("presets.json: %s" % e)

    space = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
    design = DesignResult.model_validate_json((FIXTURES / "design_result_example.json").read_text())
    if space.source.doc_url:
        problems.append("design_space_fin.json: doc_url must be null in committed fixtures")
    if canonicalize(space, design.params) != design.params:
        problems.append("design_result_example.json: params are not canonical")
    if param_hash(space, design.params) != design.param_hash:
        problems.append("design_result_example.json: param_hash mismatch")

    for rec in sorted(FIXTURES.glob("*.jsonl")):
        problems += check_recording(rec)
    problems += check_v2()

    if problems:
        print("CONTRACT CHECK FAILED (v%s):" % CONTRACT_VERSION)
        for p in problems:
            print("  -", p)
        return 1
    print("contracts v%s OK: %d fixtures + %d recording(s); v2: %d fixtures + %d recording(s)"
          % (CONTRACT_VERSION, len(SINGLE) + 1, len(list(FIXTURES.glob("*.jsonl"))),
             len(list(V2.glob("*.json"))), len(list(V2.glob("*.jsonl")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

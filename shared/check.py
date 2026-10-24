"""Validate every shared fixture against the frozen models. Run: python -m shared.check (or `make contracts`)."""
import json
import sys
from pathlib import Path
from typing import List

from shared.contracts import (
    CONTRACT_VERSION, BudgetStatus, DesignResult, DesignSpace, Goal, MetricInfo, Score, canonicalize,
    param_hash,
)
from shared.events import Event, validate_event

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

    if problems:
        print("CONTRACT CHECK FAILED (v%s):" % CONTRACT_VERSION)
        for p in problems:
            print("  -", p)
        return 1
    print("contracts v%s OK: %d fixtures + %d recording(s)"
          % (CONTRACT_VERSION, len(SINGLE) + 1, len(list(FIXTURES.glob("*.jsonl")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())

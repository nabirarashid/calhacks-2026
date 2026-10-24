"""The knowledge layer must agree with the solvers (W-B, PLAN.md v4 B4). Zero network.

domains/aero/principles.md is fed to the planner, and the planner's predictions are scored
against the solver. A principle that disagrees with the solver teaches the agent to be wrong
and drags down the prediction-accuracy curve on screen. The live Sonnet session on Sat Oct 24
hit exactly this: the seed P-INDUCED-AR listed span with induced drag "down", the solver
(correctly) raises raw induced drag with span at fixed chord, and the agent called it a
surprise.

Each principle may carry a `check:` line (ignored by the parser, never shown to the model):
a starting state and one lever step. This test applies the step and confirms every claimed
direction in `effects`, and for percentage metrics the claimed strength, against the solver.
"""
import json
import os
import re

import pytest

pytest.importorskip("aerosandbox", reason="AeroSandbox is not installed")

from domains.aero.pack import PACK, parse_principles    # noqa: E402
from shared.contracts import Goal                       # noqa: E402
from shared.manifest import ProjectManifest             # noqa: E402
from sim import api                                     # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
TEXT = open(os.path.join(ROOT, "domains", "aero", "principles.md")).read()
PRINCIPLES = parse_principles(TEXT)

# Metrics whose natural unit is absolute (degrees, calibers, mm, a margin ratio):
# for these the strength words are not percentages, so only direction is checked.
ABSOLUTE = {"stall_margin_deg", "stability_margin_cal", "flutter_margin", "aft_overhang_mm"}
FLAT_PCT, FLAT_ABS = 2.0, 0.05
# Strength bands overlap on purpose: the test catches a principle that is badly wrong
# (claiming "strong" for a 0.5 % change), not one that sits on a category boundary.
STRENGTH_BANDS = {"small": (0.0, 3.0), "moderate": (1.5, 7.0), "strong": (5.0, float("inf"))}
_EFFECT = re.compile(r"\s*([a-z_]+):\s*(up|down|flat)(?:\s*\((strong|moderate|small)\))?\s*$")


def _space(project):
    with open(os.path.join(ROOT, "projects", project, "r1.json")) as fh:
        return ProjectManifest(**json.load(fh)).design_space


WING, FIN = _space("rear_wing"), _space("fin_reference")
GOAL = Goal(source_text="", objectives=[], constraints=[])


def _checks():
    """principle id -> (overrides, lever, delta), from the raw text (the parser drops them)."""
    out, cur = {}, None
    for line in TEXT.splitlines():
        m = re.match(r"^### (P-[A-Z0-9-]+)\s*$", line)
        if m:
            cur = m.group(1)
        elif cur and line.startswith("check:"):
            body = line.split(":", 1)[1]
            parts = [x.strip() for x in body.split(";") if x.strip()]
            step = parts[-1].split()
            assert step[0] == "step", "check must end with 'step <lever> <delta>': %s" % line
            overrides = dict(kv.split("=") for kv in parts[:-1])
            out[cur] = ({k.strip(): float(v) for k, v in overrides.items()}, step[1], float(step[2]))
    return out


CHECKS = _checks()


def _evaluate(space, params):
    if space.scorer == "fin_v1":
        return api.evaluate(space, params, GOAL).metrics
    return api._plugin(space.scorer).evaluate_metrics(space, params).metrics


def _effects(principle):
    out = []
    for part in principle["effects"].split(";"):
        m = _EFFECT.match(part)
        assert m, "%s: bad effect syntax %r" % (principle["id"], part)
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def test_file_parses_with_the_backend_parser_and_hits_the_target_count():
    assert 25 <= len(PRINCIPLES) <= 35, len(PRINCIPLES)


def test_seed_ids_referenced_by_fixtures_are_kept():
    ids = {p["id"] for p in PRINCIPLES}
    assert {"P-INDUCED-AR", "P-ENDPLATE-AR", "P-AOA-LIFT", "P-FLAP-CAMBER"} <= ids


def test_every_lever_and_metric_name_is_real():
    params = {p.name for p in WING.parameters} | {p.name for p in FIN.parameters}
    metrics = ({m.name for m in api.metric_catalog("rear_wing_v1")}
               | {m.name for m in api.metric_catalog("fin_v1")})
    for p in PRINCIPLES:
        for metric, _, _ in _effects(p):
            assert metric in metrics, (p["id"], metric)
        if not p["levers"].startswith("none"):
            for lever in (x.strip() for x in p["levers"].split(",")):
                assert lever in params, (p["id"], lever)


def test_every_principle_cites_a_source():
    for p in PRINCIPLES:
        assert len(p["source"]) > 10, p["id"]


def test_ablation_still_removes_all_knowledge():
    """The intro is kept when DARWIN_KNOWLEDGE=off; it must not carry principles."""
    assert "### P-" not in PACK.prompt_fragment
    assert not any(p["id"] in PACK.prompt_fragment for p in PRINCIPLES)


def test_part_tags_match_the_levers():
    """The planner sees every principle, so a wing run must be able to tell which
    ones are about fins. Tags are checked against the levers they name."""
    wing_params = {p.name for p in WING.parameters}
    fin_params = {p.name for p in FIN.parameters}
    for p in PRINCIPLES:
        levers = set() if p["levers"].startswith("none") else {
            x.strip() for x in p["levers"].split(",")}
        if p["statement"].startswith("Rocket fin:"):
            assert levers <= fin_params, p["id"]
        elif p["statement"].startswith("Rear wing:"):
            assert levers <= wing_params, p["id"]


def test_most_principles_are_machine_checked():
    """Only strategies and model limitations, which involve no single lever step,
    may go unchecked."""
    unchecked = [p["id"] for p in PRINCIPLES if p["id"] not in CHECKS]
    assert len(unchecked) <= 7, unchecked


@pytest.mark.parametrize("pid", sorted(CHECKS))
def test_principle_effects_agree_with_the_solver(pid):
    principle = [p for p in PRINCIPLES if p["id"] == pid][0]
    overrides, lever, delta = CHECKS[pid]
    space = WING if lever in {p.name for p in WING.parameters} else FIN
    spec = [s for s in space.parameters if s.name == lever][0]
    start = {s.name: s.default for s in space.parameters}
    start.update(overrides)
    stepped = dict(start)
    stepped[lever] = start[lever] + delta
    assert spec.min <= stepped[lever] <= spec.max, "%s: check steps out of bounds" % pid

    before, after = _evaluate(space, start), _evaluate(space, stepped)
    for metric, direction, strength in _effects(principle):
        if metric in ABSOLUTE:
            change, flat = after[metric] - before[metric], FLAT_ABS
        else:
            change, flat = 100.0 * (after[metric] - before[metric]) / abs(before[metric]), FLAT_PCT
        if direction == "flat":
            assert abs(change) < flat, "%s: %s claimed flat, moved %+.3f" % (pid, metric, change)
            continue
        sign_ok = change > 0 if direction == "up" else change < 0
        assert sign_ok, "%s: %s claimed %s, moved %+.3f" % (pid, metric, direction, change)
        if strength and metric not in ABSOLUTE:
            lo, hi = STRENGTH_BANDS[strength]
            assert lo <= abs(change) <= hi, "%s: %s claimed %s, moved %+.2f %%" % (
                pid, metric, strength, change)

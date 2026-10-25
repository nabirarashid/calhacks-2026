"""C5 proof bench on the rear wing (PLAN.md C5). Writes demo/bench_wing.json.

Same simulation budget for every method, CAD off (zero Onshape calls):
  darwin         the investigator, aero principles ON
  darwin_noknow  the same, DARWIN_KNOWLEDGE=off (the ablation)
  cmaes, random  classic baselines, searching only the editable parameters
Reported per goal (lead with prediction accuracy, per W-B's pilot): prediction accuracy (Darwin
variants), final result of the best feasible design, simulations used, and simulations to reach
95% of the best value known for that goal (best of every run plus a random landscape sample).

Run (needs an LLM key): python -m backend.bench_wing [--repeats 3] [--sims 20]
The committed demo/bench_wing.json was made with Claude Sonnet 5.5 (Sat Oct 24).
"""
import argparse
import json
import os
import random
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ["DARWIN_CAD"] = "off"
os.environ.setdefault("DARWIN_SIM", "real")

from shared.contracts import Constraint, Goal, Objective, canonicalize  # noqa: E402

from backend.baselines import RUNNERS, editable_view  # noqa: E402
from backend.bus import Bus  # noqa: E402
from backend.investigator import Investigator  # noqa: E402
from backend.wiring import Wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ALL_BUT_CHORD = ["aoa_deg", "span_mm", "flap_angle_deg", "flap_chord_frac", "endplate_height_mm"]
STALL = Constraint(ref="stall_margin_deg", op=">=", value=0.5, label="Keep clear of stall")


def goals() -> Dict[str, Goal]:
    drag15 = Constraint(ref="drag_n", op="<=", value=15.0, label="Drag <= 15 N")
    return {
        "downforce_drag15": Goal(
            source_text="More downforce without going over 15 N of drag. Keep the chord.",
            objectives=[Objective(metric="downforce_n", direction="maximize")], constraints=[drag15, STALL],
            editable=ALL_BUT_CHORD, parsed_by="preset"),
        "downforce_span_fixed": Goal(
            source_text="More downforce without going over 15 N of drag. Keep the chord and the span.",
            objectives=[Objective(metric="downforce_n", direction="maximize")], constraints=[drag15, STALL],
            editable=[n for n in ALL_BUT_CHORD if n != "span_mm"], parsed_by="preset"),
        "min_drag_df120": Goal(
            source_text="Cut drag while keeping at least 120 N of downforce. Keep the chord.",
            objectives=[Objective(metric="drag_n", direction="minimize")],
            constraints=[Constraint(ref="downforce_n", op=">=", value=120.0, label="Downforce >= 120 N"), STALL],
            editable=ALL_BUT_CHORD, parsed_by="preset"),
    }


def _objective(goal: Goal) -> (str, bool):
    o = goal.objectives[0]
    return o.metric, o.direction != "minimize"


def _best(designs: List[Any], metric: str, maximize: bool) -> Optional[float]:
    vals = [d.score.metrics[metric] for d in designs if d.score.feasible]
    return (max(vals) if maximize else min(vals)) if vals else None


def _trajectory(designs: List[Any], metric: str, maximize: bool) -> List[Optional[float]]:
    out, best = [], None
    for d in designs:
        if d.score.feasible:
            v = d.score.metrics[metric]
            best = v if best is None or (v > best if maximize else v < best) else best
        out.append(best)
    return out


def run_darwin(w: Wiring, space, goal: Goal, sims: int, knowledge: bool, tag: str) -> Dict[str, Any]:
    os.environ["DARWIN_KNOWLEDGE"] = "on" if knowledge else "off"
    inv = Investigator(w, Bus().open("bench_%s_%s" % (tag, time.strftime("%H%M%S")), record=False), space, goal,
                       max_steps=12, max_sims=sims, pack=w.packs.get("rear_wing"), llm_max_spend_usd=0.30)
    t0 = time.time()
    inv.start()
    inv.thread.join(900)
    metric, maximize = _objective(goal)
    # Darwin's result is the design it applied (accepted), i.e. what would be in Onshape.
    applied = inv.current
    return {"final": applied.score.metrics[metric] if applied and applied.score.feasible else None,
            "best_seen": _best(inv.designs, metric, maximize),
            "trajectory": _trajectory(inv.designs, metric, maximize), "sims": len(inv.designs),
            "accuracy": inv.notebook.accuracy[-1] if inv.notebook.accuracy else None,
            "steps": len(inv.history), "rules_steps": sum(1 for d in inv.degradations if d.startswith("rules@")),
            "llm_usd": round(inv.llm_budget.spend_usd, 4), "seconds": round(time.time() - t0, 1)}


def run_baseline(w: Wiring, space, goal: Goal, method: str, sims: int, seed: int) -> Dict[str, Any]:
    start = {p.name: p.default for p in space.parameters}
    sub, sub_eval, default, sub_goal = editable_view(space, goal, start, w.sim.evaluate)
    designs = RUNNERS[method](sub, sub_goal, sub_eval, sims, seed, "bench_%s" % method, 6, default)
    metric, maximize = _objective(goal)
    return {"final": _best(designs, metric, maximize), "best_seen": _best(designs, metric, maximize),
            "trajectory": _trajectory(designs, metric, maximize), "sims": len(designs)}


def landscape_best(w: Wiring, space, goal: Goal, n: int, seed: int = 0) -> Optional[float]:
    rng = random.Random(seed)
    metric, maximize = _objective(goal)
    start = {p.name: p.default for p in space.parameters}
    best = None
    for _ in range(n):
        p = dict(start)
        for q in space.parameters:
            if q.name in (goal.editable or []):
                p[q.name] = rng.uniform(float(q.min), float(q.max))
        s = w.sim.evaluate(space, canonicalize(space, p), goal)
        if s.feasible:
            v = s.metrics[metric]
            best = v if best is None or (v > best if maximize else v < best) else best
    return best


def sims_to(traj: List[Optional[float]], target: float, maximize: bool) -> Optional[int]:
    for i, v in enumerate(traj, 1):
        if v is not None and (v >= target if maximize else v <= target):
            return i
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sims", type=int, default=20)
    ap.add_argument("--landscape", type=int, default=600)
    ap.add_argument("--goals", default="", help="comma-separated goal names (default: all)")
    ap.add_argument("--out", default=str(ROOT / "demo" / "bench_wing.json"))
    args = ap.parse_args()
    w = Wiring()
    space = w.resolve("rear_wing")
    chosen = {k: g for k, g in goals().items() if not args.goals or k in args.goals.split(",")}
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "solver_mode": w.modes.get("rear_wing_v1", "real"),
           "sims_budget": args.sims, "repeats": args.repeats, "goals": {}}
    for name, goal in chosen.items():
        metric, maximize = _objective(goal)
        runs = {"darwin": [], "darwin_noknow": [], "cmaes": [], "random": []}  # type: Dict[str, List[Dict]]
        for r in range(1, args.repeats + 1):
            for method in ("darwin", "darwin_noknow"):
                res = run_darwin(w, space, goal, args.sims, method == "darwin", "%s_%s_%d" % (name, method, r))
                runs[method].append(res)
                print("%-22s %-14s rep %d  final %s  acc %s  sims %d  rules %d  $%.3f  %ss" % (
                    name, method, r, res["final"], res["accuracy"], res["sims"], res["rules_steps"],
                    res["llm_usd"], res["seconds"]), flush=True)
            for method in ("cmaes", "random"):
                res = run_baseline(w, space, goal, method, args.sims, r)
                runs[method].append(res)
                print("%-22s %-14s rep %d  final %s  sims %d" % (name, method, r, res["final"], res["sims"]), flush=True)
        seen = [x["best_seen"] for rs in runs.values() for x in rs if x["best_seen"] is not None]
        land = landscape_best(w, space, goal, args.landscape)
        pool = seen + ([land] if land is not None else [])
        best_known = (max(pool) if maximize else min(pool)) if pool else None
        target = None if best_known is None else (0.95 * best_known if maximize else 1.05 * best_known)
        summary = {}
        for method, rs in runs.items():
            finals = [x["final"] for x in rs if x["final"] is not None]
            reach = [sims_to(x["trajectory"], target, maximize) for x in rs] if target is not None else []
            row = {"median_final": statistics.median(finals) if finals else None, "finals": [x["final"] for x in rs],
                   "median_sims": statistics.median([x["sims"] for x in rs]),
                   "reached_95pct": sum(1 for x in reach if x is not None),
                   "median_sims_to_95pct": statistics.median([x for x in reach if x is not None])
                   if any(x is not None for x in reach) else None}
            if method.startswith("darwin"):
                accs = [x["accuracy"] for x in rs if x["accuracy"] is not None]
                row.update(median_accuracy=statistics.median(accs) if accs else None,
                           llm_usd=round(sum(x["llm_usd"] for x in rs), 4),
                           rules_steps=sum(x["rules_steps"] for x in rs))
            summary[method] = row
        out["goals"][name] = {"objective": metric, "maximize": maximize, "editable": goal.editable,
                              "best_known": best_known, "landscape_best": land, "summary": summary, "runs": runs}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=2) + "\n")          # save after every goal
        print("== %s: best known %s | %s" % (name, best_known, {m: (s["median_final"], s.get("median_accuracy"))
                                                              for m, s in summary.items()}), flush=True)
    print("wrote", args.out)


if __name__ == "__main__":
    main()

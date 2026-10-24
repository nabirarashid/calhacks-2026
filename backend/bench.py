"""Agent vs CMA-ES vs random on matched budgets (PLAN.md v3 MS-2). Writes demo/bench.json.

Run: DARWIN_LLM_PROVIDER=anthropic python -m backend.bench [--seeds 3] [--out demo/bench.json]
Never touches Onshape (DARWIN_CAD is forced off and the bench profile skips geometry).
Goals are the presets (no goal-parser variance). For each goal the "oracle" is the best
aggregate seen anywhere: a landscape sample plus every design any method evaluated.
Numbers in the output are what the pitch may quote; one seed proves nothing.
"""
import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ["DARWIN_CAD"] = "off"

from shared.contracts import RunConfig  # noqa: E402

from backend.bus import Bus  # noqa: E402
from backend.run_loop import RunController, new_run_id  # noqa: E402
from backend.wiring import Wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
METHODS = ("agent", "cmaes", "random")


def _evals_to(curve: List[Dict[str, Any]], threshold: float) -> Optional[int]:
    return next((p["evals"] for p in curve if p["best_aggregate"] >= threshold), None)


def run_one(w: Wiring, bus: Bus, preset: Any, seed: int) -> Dict[str, Any]:
    space = w.spaces["fin_v1"]
    ctl = RunController(w, bus.open(new_run_id("bench"), record=False), space, preset.goal,
                        RunConfig(seed=seed, profile="bench", baselines=["cmaes", "random"]))
    t0 = time.time()
    ctl.start()
    ctl.thread.join(600)
    summary = ctl.ch.events[-1]["payload"]["summary"]
    seen = [e["payload"]["design"]["score"]["aggregate"] for e in ctl.ch.events if e["type"] == "design_evaluated"]
    for hist in ctl.baseline_results.values():
        seen += [d.score.aggregate for d in hist]
    best = {"agent": summary["champion"]["score"]["aggregate"] if summary.get("champion") else None}
    for m in ("cmaes", "random"):
        b = summary["baseline_best"].get(m)
        best[m] = b["score"]["aggregate"] if b else None
    budget = (summary.get("budget") or {}).get("model", {})
    return {"goal": preset.label, "seed": seed, "best": best, "curves": summary["curves"],
            "evals": summary["curves"]["agent"][-1]["evals"] if summary["curves"].get("agent") else None,
            "seen_max": max(seen) if seen else None, "degradations": summary["degradations"],
            "llm_usd": budget.get("spend_run_usd"), "llm_calls": budget.get("calls_run"),
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--goals", type=str, default="", help="comma-separated preset labels (default: all)")
    ap.add_argument("--landscape-n", type=int, default=1200)
    ap.add_argument("--out", type=str, default=str(ROOT / "demo" / "bench.json"))
    args = ap.parse_args()

    w, bus = Wiring(), Bus()
    wanted = [g.strip() for g in args.goals.split(",") if g.strip()]
    presets = [p for p in w.presets if not wanted or p.label in wanted]
    runs = []  # type: List[Dict[str, Any]]
    for p in presets:
        for seed in range(1, args.seeds + 1):
            r = run_one(w, bus, p, seed)
            runs.append(r)
            print("%-24s seed %d  agent %+.3f  cmaes %+.3f  random %+.3f  (%s s, $%s)"
                  % (p.label, seed, r["best"]["agent"], r["best"]["cmaes"], r["best"]["random"], r["seconds"],
                     r["llm_usd"]), flush=True)

    space = w.spaces["fin_v1"]
    goals = {}  # type: Dict[str, Any]
    for p in presets:
        rs = [r for r in runs if r["goal"] == p.label]
        land = w.sim.landscape(space, p.goal, n=args.landscape_n, seed=0)
        oracle = max([s.aggregate for _, s in land] + [r["seen_max"] for r in rs if r["seen_max"] is not None])
        per = {}
        for m in METHODS:
            finals = [r["best"][m] for r in rs if r["best"][m] is not None]
            reach = [_evals_to(r["curves"].get(m, []), 0.95 * oracle) for r in rs]
            per[m] = {"median_best": statistics.median(finals) if finals else None,
                      "finals": finals,
                      "median_pct_of_oracle": statistics.median([f / oracle * 100 for f in finals])
                      if finals and oracle > 0 else None,
                      "reached_95pct": sum(1 for x in reach if x is not None),
                      "median_evals_to_95pct": statistics.median([x for x in reach if x is not None])
                      if any(x is not None for x in reach) else None}
        wins = sum(1 for r in rs if r["best"]["agent"] is not None and r["best"]["cmaes"] is not None
                   and r["best"]["agent"] > r["best"]["cmaes"])
        goals[p.label] = {"oracle": oracle, "methods": per, "agent_beats_cmaes": "%d/%d" % (wins, len(rs))}

    total_wins = sum(int(g["agent_beats_cmaes"].split("/")[0]) for g in goals.values())
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "design_space": space.id,
           "edge_profile": "square (live Part Studio)", "seeds": args.seeds,
           "budget_evals": RunConfig().budget(), "llm_provider": w.modes.get("llm"),
           "agent_beats_cmaes": "%d/%d" % (total_wins, len(runs)),
           "llm_usd_total": round(sum(r["llm_usd"] or 0.0 for r in runs), 4),
           "goals": goals, "runs": runs}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print("agent beats CMA-ES in %s runs; wrote %s" % (out["agent_beats_cmaes"], args.out))


if __name__ == "__main__":
    main()

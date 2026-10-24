"""Standalone S2 performance check for the frozen acceptance targets.

Run from the repository root with ``python -m sim.bench``.  Runtime cache data
is written only beneath the ignored ``.darwin/`` directory.
"""
import argparse
import json
import time
from pathlib import Path

from shared.contracts import DesignSpace, Goal
from sim.aero import warm_up
from sim.api import evaluate_batch
from sim.landscape import landscape, latin_hypercube_params


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "shared" / "fixtures"


def _load() -> tuple:
    space = DesignSpace.model_validate_json(
        (FIXTURES / "design_space_fin.json").read_text(encoding="utf-8")
    )
    goal = Goal.model_validate_json(
        (FIXTURES / "goal_example.json").read_text(encoding="utf-8")
    )
    return space, goal


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Darwin S2")
    parser.add_argument("--landscape-n", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=911)
    args = parser.parse_args()

    space, goal = _load()
    warm_up()
    batch_params = latin_hypercube_params(space, 64, args.seed)
    started = time.perf_counter()
    batch = evaluate_batch(space, batch_params, goal, workers=0)
    batch_seconds = time.perf_counter() - started

    cache_dir = ROOT / ".darwin" / "bench-landscape"
    landscape_params = latin_hypercube_params(space, args.landscape_n, args.seed)
    started = time.perf_counter()
    results = landscape(
        space,
        goal,
        n=args.landscape_n,
        seed=args.seed,
        batch_evaluate_fn=evaluate_batch,
        workers=args.workers,
        cache_dir=cache_dir,
    )
    landscape_seconds = time.perf_counter() - started

    summary = {
        "batch_64_seconds": round(batch_seconds, 4),
        "batch_64_pass": len(batch) == 64 and batch_seconds < 1.5,
        "landscape_n": len(results),
        "landscape_seconds": round(landscape_seconds, 4),
        "landscape_pass": (
            len(results) == len(landscape_params)
            and (args.landscape_n != 2000 or landscape_seconds < 25.0)
        ),
        "workers": args.workers,
        "warned_batch_designs": sum(bool(score.warnings) for score in batch),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary["batch_64_pass"] or not summary["landscape_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


"""Write shared/fixtures/sample_run.jsonl (+ fixtures/geometry/*.stl) from the three fakes.

Run: python -m shared.mocks.make_sample_run [--seed 7]
A compact, deterministic stand-in for the backend run loop on a simulated clock
(no sleeps). It emits every event type in B.8 order so S4 can build the whole UI
against it. Not the real loop: that is backend/run_loop.py.
"""
import argparse
import json
import os
import random
import re
from pathlib import Path
from typing import Dict, List, Optional

from shared.contracts import (
    AgentMessage, BudgetStatus, CurvePoint, DesignResult, DesignSpace, Directive, Generation, Goal,
    ModelBudget, RunConfig, RunSummary, Score, canonicalize, make_design_id, param_hash,
)
from shared.events import (
    AgentMessageEvent, BaselineProgress, BudgetUpdate, ChampionUpdated, DesignEvaluated, ErrorEvent,
    GenerationComplete, GeometryReady, LandscapeReady, RunComplete, RunStarted, make_event,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
RUN_ID = "run_0712_3fa9"
T0 = 1761278400.0          # Fri 2026-10-24 04:00 UTC; any fixed epoch works


class Recorder:
    def __init__(self) -> None:
        self.t = T0
        self.seq = 0
        self.lines = []  # type: List[str]

    def tick(self, seconds: float) -> None:
        self.t += seconds

    def emit(self, type_: str, payload) -> None:
        self.seq += 1
        self.lines.append(make_event(type_, RUN_ID, self.seq, round(self.t, 3), payload).model_dump_json())


def _extract(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    os.environ["FAKE_CAD_LATENCY"] = "0"
    os.environ["FAKE_LLM_LATENCY"] = "0"
    os.environ["DARWIN_CACHE_DIR"] = str(FIXTURES)          # fake_cad writes fixtures/geometry/
    os.environ["FAKE_CAD_SUBDIR"] = "geometry"
    geo_dir = FIXTURES / "geometry"
    if geo_dir.exists():
        for f in geo_dir.iterdir():
            f.unlink()
    from shared.mocks import fake_cad, fake_llm, fake_sim   # after env is set

    space = DesignSpace.model_validate_json((FIXTURES / "design_space_fin.json").read_text())
    goal = Goal.model_validate_json((FIXTURES / "goal_example.json").read_text())
    config = RunConfig(seed=args.seed)
    N, G, budget = config.population, config.generations, config.budget()
    catalog = fake_sim.metric_catalog(space.scorer)
    rng = random.Random(args.seed)
    rec = Recorder()
    llm_calls = 0

    def budget_status(evals: int) -> BudgetStatus:
        return BudgetStatus(onshape=fake_cad.budget_status(),
                            model=ModelBudget(provider="mock", calls_run=llm_calls, calls_cap_run=config.llm_max_calls,
                                              spend_run_usd=0.0, spend_cap_run_usd=config.llm_max_spend_usd,
                                              spend_total_usd=0.0, spend_cap_total_usd=4.5),
                            evals_used=evals, evals_budget=budget)

    def msg(agent: str, kind: str, gen: Optional[int], summary: str, body: str = "", refs=None,
            latency: float = 0.0) -> None:
        rec.emit("agent_message", AgentMessageEvent(message=AgentMessage(
            message_id="m%03d" % (rec.seq + 1), run_id=RUN_ID, generation=gen, agent=agent, kind=kind,  # type: ignore[arg-type]
            model="mock" if agent not in ("system",) else "rules", summary=summary, body=body, refs=refs or [],
            tokens_in=900, tokens_out=350, cost_usd=0.0, latency_ms=latency * 1000)))

    summary = RunSummary(run_id=RUN_ID, status="running", goal=goal, design_space_id=space.id, config=config,
                         started_at="2026-10-24T04:00:00Z")
    rec.emit("run_started", RunStarted(summary=summary, design_space=space, metric_catalog=catalog))

    designs = []  # type: List[DesignResult]
    seen = set()
    curves = {"agent": [], "cmaes": [], "random": []}  # type: Dict[str, List[CurvePoint]]
    champion = None  # type: Optional[DesignResult]
    best_so_far = -1e9
    builds = 0
    stagnation = 0
    directive = Directive(mode="explore", n_explore=N // 2, step_scale=0.15, reason="first generation")

    def record(params: Dict, gen: int, origin: str, idx: int, parents: List[str], op: str, why: str) -> DesignResult:
        score = fake_sim.evaluate(space, params, goal)
        d = DesignResult(design_id=make_design_id(RUN_ID, gen, origin, idx), run_id=RUN_ID, generation=gen,
                         origin=origin, params=canonicalize(space, params), param_hash=param_hash(space, params),  # type: ignore[arg-type]
                         parent_ids=parents, operator=op, rationale=why, score=score,
                         timings_ms={"propose": 2600.0, "eval": round(score.eval_ms, 3)})
        designs.append(d)
        seen.add(d.param_hash)
        return d

    # --- baselines (precomputed; streamed per generation below) ---
    import cma
    base_hist = {"cmaes": [], "random": []}  # type: Dict[str, List[DesignResult]]
    default = canonicalize(space, {})
    for i in range(budget):
        p = default if i == 0 else fake_sim.random_params(space, rng)
        base_hist["random"].append(_baseline_design(space, goal, p, "baseline_random", i, fake_sim))
    cont = [s for s in space.parameters if s.kind != "choice"]
    choice = [s for s in space.parameters if s.kind == "choice"]

    def decode(x: List[float]) -> Dict:
        out = {}
        for s, v in zip(cont + choice, x):
            v = min(1.0, max(0.0, v))
            if s.kind == "choice":
                out[s.name] = s.choices[min(len(s.choices) - 1, int(v * len(s.choices)))]  # type: ignore[index]
            else:
                out[s.name] = s.min + v * (s.max - s.min)  # type: ignore[operator]
        return out

    def encode(p: Dict) -> List[float]:
        x = [(float(p[s.name]) - s.min) / (s.max - s.min) for s in cont]  # type: ignore[operator]
        x += [(s.choices.index(p[s.name]) + 0.5) / len(s.choices) for s in choice]  # type: ignore[union-attr]
        return x

    es = cma.CMAEvolutionStrategy(encode(default), 0.25, {"popsize": N, "seed": args.seed, "verbose": -9,
                                                           "bounds": [0, 1]})
    i = 0
    while i < budget:
        xs = es.ask()
        fit = []
        for x in xs:
            p = default if i == 0 else decode(list(x))
            d = _baseline_design(space, goal, p, "baseline_cmaes", i, fake_sim)
            base_hist["cmaes"].append(d)
            fit.append(-d.score.aggregate)
            i += 1
            if i >= budget:
                break
        if len(fit) == len(xs):
            es.tell(xs, fit)

    def baseline_tick(evals: int) -> None:
        for method in ("cmaes", "random"):
            hist = base_hist[method][:evals]
            best = max(hist, key=lambda d: d.score.aggregate)
            cp = CurvePoint(evals=evals, best_aggregate=best.score.aggregate)
            curves[method].append(cp)
            rec.emit("baseline_progress", BaselineProgress(method=method, evals_used=evals,  # type: ignore[arg-type]
                                                          best_aggregate=best.score.aggregate, best=best,
                                                          curve_point=cp))

    seed_design = None  # type: Optional[DesignResult]
    for g in range(G):
        # propose
        n = N - 1 if g == 0 else N
        top = sorted(designs, key=lambda d: d.score.aggregate, reverse=True)[:6]
        block = {"n": n, "params": [s.model_dump(mode="json") for s in space.parameters],
                 "top": [{"design_id": d.design_id, "params": d.params, "aggregate": d.score.aggregate} for d in top],
                 "directive": directive.model_dump(mode="json")}
        user = "Propose designs.\n```json\n%s\n```" % json.dumps(block)
        res = fake_llm.call_model("proposer", "sys", user)
        llm_calls += 1
        data = _extract(res.raw_text) or {}
        props = data.get("proposals")
        if not isinstance(props, list):
            rec.emit("error", ErrorEvent(component="llm", code="invalid_json",
                                         message="proposer output failed validation at g%d" % g, recoverable=True,
                                         degraded_to="fallback_proposer"))
            props = [{"params": {k: v for k, v in fake_sim.random_params(space, rng).items()}, "parent_ids": [],
                      "operator": "mutate", "rationale": "fallback GA mutation"} for _ in range(n)]
            origin = "fallback"
        else:
            origin = "agent"
        rec.tick(2.6)
        msg("proposer", "proposal", g, "Proposed %d designs: %s" % (len(props), data.get("hypothesis", "fallback")),
            latency=2.6)

        gen_designs = []
        if g == 0:
            seed_design = record(default, 0, "seed", 0, [], "seed", "Default design from the Part Studio.")
            gen_designs.append(seed_design)
        for j, prop in enumerate(props):
            try:
                params = canonicalize(space, prop.get("params", {}))
            except ValueError:
                continue
            if param_hash(space, params) in seen:
                params = fake_sim.random_params(space, rng)
            gen_designs.append(record(params, g, origin, j + 1, prop.get("parent_ids", []),
                                      prop.get("operator", "mutate"), prop.get("rationale", "")))
        ranks = fake_sim.pareto_ranks([d.score for d in designs], goal)
        for d, r in zip(designs, ranks):
            d.pareto_rank = r
        for d in gen_designs:
            rec.tick(0.05)
            rec.emit("design_evaluated", DesignEvaluated(design=d))
        evals = len(designs)

        # champion + geometry
        best = max(designs, key=lambda d: d.score.aggregate)
        improved = best.score.aggregate - best_so_far
        if champion is None or best.design_id != champion.design_id:
            prev = champion.design_id if champion else None
            rec.emit("champion_updated", ChampionUpdated(design_id=best.design_id, previous_id=prev,
                                                          aggregate=best.score.aggregate,
                                                          delta=round(improved if prev else 0.0, 5),
                                                          reason="best feasible aggregate so far"))
            champion = best
            if (prev is None or improved >= config.geometry_min_improvement) and builds < config.geometry_max_builds:
                builds += 1
                geo = fake_cad.build_geometry(space, best.params)
                best.geometry = geo
                rec.tick(1.7)
                rec.emit("geometry_ready", GeometryReady(design_id=best.design_id, geometry=geo))
        stagnation = 0 if improved >= config.min_improvement else stagnation + 1
        best_so_far = max(best_so_far, best.score.aggregate)
        curves["agent"].append(CurvePoint(evals=evals, best_aggregate=round(best_so_far, 5)))

        if g == 1:
            pts = [[round(s.metrics["drag_n"], 4), round(s.metrics["stability_margin_cal"], 4),
                    round(s.aggregate, 4), s.feasible] for _, s in fake_sim.landscape(space, goal)]
            rec.emit("landscape_ready", LandscapeReady(metrics=["drag_n", "stability_margin_cal"], points=pts,
                                                       n=len(pts)))

        # critic (async in the real loop)
        rec.tick(1.4)
        sens = fake_sim.sensitivity(space, champion.params, goal)
        cblock = {"champion": {"design_id": champion.design_id, "params": champion.params,
                               "metrics": champion.score.metrics}, "sensitivity": sens}
        cres = fake_llm.call_model("critic", "sys", "Explain.\n```json\n%s\n```" % json.dumps(cblock))
        llm_calls += 1
        cdata = _extract(cres.raw_text) or {}
        why = cdata.get("why_winner_won", "Champion holds its lead; no new evidence this generation.")
        msg("critic", "insight", g, why, body="\n".join("- " + s for s in cdata.get("insights", [])),
            refs=[champion.design_id], latency=1.4)
        warned = [d for d in gen_designs if d.score.warnings]
        if warned:
            msg("critic", "warning", g, "%s: %s" % (warned[0].design_id, warned[0].score.warnings[0]),
                refs=[warned[0].design_id])

        if g % 3 == 2 or stagnation >= 2:
            sres = fake_llm.call_model("strategist", "sys",
                                       "Decide.\n```json\n%s\n```" % json.dumps({"generation": g, "stagnation": stagnation}))
            llm_calls += 1
            sdata = _extract(sres.raw_text) or {}
            try:
                directive = Directive(source="llm", **sdata)
            except Exception:  # noqa: BLE001 — rules fallback, as in the real loop
                directive = Directive(mode="explore" if stagnation >= 2 else "exploit", n_explore=2, source="rules",
                                      reason="rules fallback")
            msg("strategist", "directive", g, "%s (%s)" % (directive.mode, directive.reason))

        baseline_tick(evals)
        pareto_ids = [d.design_id for d in designs if d.pareto_rank == 0 and d.origin != "baseline_cmaes"]
        rec.emit("generation_complete", GenerationComplete(generation=Generation(
            run_id=RUN_ID, index=g, design_ids=[d.design_id for d in gen_designs], champion_id=champion.design_id,
            best_aggregate=champion.score.aggregate,
            mean_aggregate=round(sum(d.score.aggregate for d in gen_designs) / len(gen_designs), 5),
            feasible_count=sum(1 for d in gen_designs if d.score.feasible), evals_used=evals, evals_budget=budget,
            directive=directive, critic_summary=why, elapsed_ms=5800.0), pareto_ids=pareto_ids))
        rec.emit("budget_update", BudgetUpdate(budget=budget_status(evals)))

    # final
    assert champion is not None
    rec.tick(2.0)
    hifi = fake_sim.validate_high_fidelity(space, champion.params, goal)
    msg("reporter", "report", None, "Final report: %s beats the seed on %d of %d objectives."
        % (champion.design_id, sum(1 for k, v in champion.score.objective_scores.items()
                                   if v > (seed_design.score.objective_scores.get(k, 0) if seed_design else 0)),
           len(goal.objectives)), body="Numbers in this report come from the simulation, not the model.",
        refs=[champion.design_id], latency=4.2)
    final = summary.model_copy(update={
        "status": "complete", "finished_at": "2026-10-24T04:01:00Z", "champion": champion, "seed_design": seed_design,
        "baseline_best": {m: max(base_hist[m], key=lambda d: d.score.aggregate) for m in base_hist},
        "curves": curves, "pareto_ids": [d.design_id for d in designs if d.pareto_rank == 0],
        "hifi_check": hifi, "budget": budget_status(len(designs)), "degradations": [],
        "recording": "sample_run.jsonl"})
    rec.emit("run_complete", RunComplete(summary=final))

    out = FIXTURES / "sample_run.jsonl"
    out.write_text("\n".join(rec.lines) + "\n")
    print("wrote %s: %d events, %d designs, champion %s (%.3f), cmaes best %.3f, random best %.3f"
          % (out.name, len(rec.lines), len(designs), champion.design_id, champion.score.aggregate,
             final.baseline_best["cmaes"].score.aggregate, final.baseline_best["random"].score.aggregate))


def _baseline_design(space: DesignSpace, goal: Goal, params: Dict, origin: str, i: int, fake_sim) -> DesignResult:
    p = canonicalize(space, params)
    score = fake_sim.evaluate(space, p, goal)  # type: Score
    return DesignResult(design_id=make_design_id(RUN_ID, i // 8, origin, i % 8), run_id=RUN_ID, generation=i // 8,
                        origin=origin, params=p, param_hash=param_hash(space, p), operator="seed" if i == 0 else "novel",
                        score=score)


if __name__ == "__main__":
    main()

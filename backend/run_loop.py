"""The evolutionary run loop (PLAN.md S3). One RunController per run, on its own thread.

Order per generation: propose -> validate/repair/dedupe -> evaluate_batch ->
design_evaluated xN -> champion_updated? -> (geometry async) -> critic (async) ->
strategist (every 3rd gen or on stagnation) -> baseline_progress -> generation_complete
-> budget_update. Agent and baselines get exactly config.budget() evaluations.
"""
import copy
import logging
import queue
import random
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from shared.contracts import (
    AgentMessage, BudgetStatus, CurvePoint, DesignResult, DesignSpace, Directive, Generation, GeometryRef, Goal,
    ModelBudget, ModelResult, ParamValue, Proposal, RunConfig, RunSummary, Score, canonicalize, make_design_id,
    param_hash,
)
from shared.events import (
    AgentMessageEvent, BaselineProgress, BudgetUpdate, ChampionUpdated, DesignEvaluated, ErrorEvent,
    GenerationComplete, GeometryReady, LandscapeReady, RunComplete, RunStarted,
)

from backend import llm
from backend.agents import critic, proposer, reporter, strategist
from backend.agents.base import RunHistory
from backend.agents.fallback import ga_propose, mutate
from backend.baselines import RUNNERS
from backend.bus import Channel
from backend.wiring import Wiring

log = logging.getLogger("darwin.run")


def new_run_id(prefix: str = "run") -> str:
    return "%s_%s_%s" % (prefix, time.strftime("%H%M"), uuid.uuid4().hex[:4])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunController:
    def __init__(self, w: Wiring, channel: Channel, space: DesignSpace, goal: Goal, config: RunConfig) -> None:
        self.w = w
        self.ch = channel
        self.run_id = channel.run_id
        self.space = space
        self.goal = goal
        self.config = config
        self.N = config.population
        self.budget_evals = config.budget()
        self.history = RunHistory(space, goal, config.generations)
        self.llm_budget = llm.RunLLMBudget(config.llm_max_calls, config.llm_max_spend_usd)
        self.rng = random.Random(config.seed)
        self.degradations = []  # type: List[str]
        self.curves = {"agent": []}  # type: Dict[str, List[CurvePoint]]
        self.baseline_results = {}  # type: Dict[str, List[DesignResult]]
        self.base_futures = {}  # type: Dict[str, Future]
        self.stop_flag = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="run-%s" % self.run_id)
        self.critic_futures = []  # type: List[Future]
        self.strategist_future = None  # type: Optional[Future]
        self.last_critic_why = None  # type: Optional[str]
        self.geo_q = queue.Queue()  # type: queue.Queue
        self.builds = 0
        self.lock = threading.RLock()
        self.closed = False
        self.landscape_future = None  # type: Optional[Future]
        self.summary = RunSummary(run_id=self.run_id, status="running", goal=goal, design_space_id=space.id,
                                  config=config, started_at=_now_iso())
        self.thread = threading.Thread(target=self._main, name="run-%s" % self.run_id, daemon=True)

    # ------------------------------------------------------------ plumbing

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def emit(self, type_: str, payload: Any) -> None:
        with self.lock:
            if self.closed:          # contract: run_complete is the last event of a run
                log.info("dropping late %s for %s", type_, self.run_id)
                return
            if type_ == "run_complete":
                self.closed = True
            self.ch.emit(type_, payload)

    def message(self, agent: str, kind: str, summary: str, body: str = "", refs: Optional[List[str]] = None,
                res: Optional[ModelResult] = None, generation: Optional[int] = None,
                model: Optional[str] = None) -> None:
        self.emit("agent_message", AgentMessageEvent(message=AgentMessage(
            message_id=uuid.uuid4().hex[:10], run_id=self.run_id,
            generation=self.history.generation if generation is None else generation,
            agent=agent, kind=kind, model=model or (res.model if res else "rules"), summary=summary[:300],  # type: ignore[arg-type]
            body=body[:2000],
            refs=refs or [], tokens_in=res.tokens_in if res else 0, tokens_out=res.tokens_out if res else 0,
            cost_usd=res.cost_usd if res else 0.0, latency_ms=res.latency_ms if res else 0.0)))

    def error(self, component: str, code: str, message: str, degraded_to: Optional[str] = None) -> None:
        self.emit("error", ErrorEvent(component=component, code=code, message=message[:300], recoverable=True,  # type: ignore[arg-type]
                                      degraded_to=degraded_to))

    def budget_status(self) -> BudgetStatus:
        try:
            onshape = self.w.cad.budget_status()
        except Exception as e:  # noqa: BLE001 — budget display must never kill a run
            log.warning("cad.budget_status failed: %s", e)
            from shared.contracts import OnshapeBudget
            onshape = OnshapeBudget(account_label="unknown", calls_session=0, calls_ledger_total=0,
                                    remaining_estimate=0, reserve=0, reserve_unlocked=False, hard_stop=True)
        return BudgetStatus(
            onshape=onshape,
            model=ModelBudget(provider=llm.provider_name(), calls_run=self.llm_budget.calls,
                              calls_cap_run=self.llm_budget.max_calls, spend_run_usd=round(self.llm_budget.spend_usd, 5),
                              spend_cap_run_usd=self.llm_budget.max_spend_usd,
                              spend_total_usd=round(llm.SpendLedger.read()["total_usd"], 5),
                              spend_cap_total_usd=llm.SpendLedger.cap()),
            evals_used=len(self.history.designs), evals_budget=self.budget_evals)

    # ------------------------------------------------------------ main

    def _main(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — always end the stream cleanly
            log.exception("run %s crashed", self.run_id)
            self.error("backend", "crash", "%s: %s" % (type(e).__name__, e))
            self.summary.status = "failed"
            self.summary.finished_at = _now_iso()
            self.emit("run_complete", RunComplete(summary=self.summary))
        finally:
            self.geo_q.put(None)
            self.pool.shutdown(wait=False)

    def _run(self) -> None:
        sim, space, goal, cfg = self.w.sim, self.space, self.goal, self.config
        catalog = self.w.catalog(space.scorer)
        self.catalog = catalog
        self.emit("run_started", RunStarted(summary=self.summary, design_space=self.w.public_space(space),
                                            metric_catalog=catalog))
        default = canonicalize(space, dict(goal.fixed_params))

        self.base_futures = base_futures = {m: self.pool.submit(RUNNERS[m], space, goal, sim.evaluate, self.budget_evals, cfg.seed,
                                            self.run_id, self.N, default) for m in cfg.baselines}
        if cfg.profile != "bench":
            self.landscape_future = self.pool.submit(self._landscape)
            threading.Thread(target=self._geometry_worker, name="geo-%s" % self.run_id, daemon=True).start()

        seed = self._make_design(default, 0, "seed", 0, [], "seed", "Default design from the Part Studio.", {})
        self._evaluate_and_publish([seed], 0.0)
        self.summary.seed_design = seed

        for g in range(cfg.generations):
            if self.stop_flag.is_set():
                break
            h = self.history
            h.generation = g
            remaining = self.budget_evals - len(h.designs)
            n = min(self.N - 1 if g == 0 else self.N, remaining)
            if n <= 0:
                break
            t0 = time.perf_counter()
            directive = h.directive
            sens = self._sensitivity()
            batch = self._propose(n, directive, sens)
            propose_ms = (time.perf_counter() - t0) * 1000.0
            self._evaluate_and_publish(batch, propose_ms / max(1, len(batch)))
            self._after_generation(g, sens, t0)
            # early stop only in the last quarter, so a plateau never ends a run before the search had a chance
            if self.history.stagnation >= cfg.early_stop_patience and g + 1 >= 0.75 * cfg.generations \
                    and g < cfg.generations - 1:
                self.message("system", "status", "Early stop: no improvement >= %.3f for %d generations."
                             % (cfg.min_improvement, cfg.early_stop_patience))
                break

        self._finish(base_futures)

    # ------------------------------------------------------------ steps

    def _sensitivity(self) -> Dict[str, Dict[str, float]]:
        champ = self.history.champion
        if champ is None:
            return {}
        try:
            return self.w.sim.sensitivity(self.space, champ.params, self.goal)
        except Exception as e:  # noqa: BLE001
            log.warning("sensitivity failed: %s", e)
            return {}

    def _propose(self, n: int, directive: Directive, sens: Dict[str, Dict[str, float]]) -> List[DesignResult]:
        h = self.history
        origin = "agent"
        try:
            props, hypothesis, res = proposer.propose(h, n, directive, sens, budget=self.llm_budget)
            self.message("proposer", "proposal", "Gen %d: %s" % (h.generation, hypothesis or "%d proposals" % len(props)),
                         body="\n".join("- %s: %s" % (p.operator, p.rationale) for p in props), res=res)
        except (llm.LLMUnavailable, llm.BudgetExceeded) as e:
            origin = "fallback"
            tag = "llm_fallback@g%d" % h.generation
            if tag not in self.degradations:
                self.degradations.append(tag)
            self.error("llm", "budget" if isinstance(e, llm.BudgetExceeded) else "unavailable",
                       "proposer: %s" % e, degraded_to="fallback_proposer")
            props = ga_propose(h, n, directive, self.rng)
            self.message("proposer", "status", "Gen %d: GA fallback proposed %d designs (LLM unavailable)."
                         % (h.generation, len(props)))
        while len(props) < n:      # LLM returned too few: top up from the GA (labeled fallback)
            props += [p.model_copy(update={"rationale": "GA top-up: " + p.rationale})
                      for p in ga_propose(h, n - len(props), directive, self.rng)]
        return self._validate(props[:n], origin, directive)

    def _validate(self, props: List[Proposal], origin: str, directive: Directive) -> List[DesignResult]:
        """canonicalize (repair), enforce fixed params, reject duplicates (refill from GA, uncounted)."""
        h, space = self.history, self.space
        out = []  # type: List[DesignResult]
        batch_hashes = set()
        for idx, prop in enumerate(props):
            o, op, why, parents = origin, prop.operator, prop.rationale, [p for p in prop.parent_ids if p in h.by_id]
            try:
                canon = canonicalize(space, dict(prop.params, **self.goal.fixed_params))
                if self._repaired(prop.params, canon):
                    op, why = "repair", ("clamped into bounds; " + why)[:200]
            except ValueError as e:
                base = h.champion.params if h.champion else canonicalize(space, {})
                canon = canonicalize(space, dict(mutate(space, base, self.rng, directive.step_scale, []),
                                                 **self.goal.fixed_params))
                o, op, why = "fallback", "mutate", "invalid proposal (%s); GA replacement" % str(e)[:80]
            tries = 0
            while (param_hash(space, canon) in h.hashes or param_hash(space, canon) in batch_hashes) and tries < 8:
                base = canon if tries < 4 else (h.champion.params if h.champion else canon)
                canon = canonicalize(space, dict(mutate(space, base, self.rng, max(0.05, directive.step_scale), []),
                                                 **self.goal.fixed_params))
                o, op, why, tries = "fallback", "mutate", "duplicate of an earlier design; GA perturbation", tries + 1
            batch_hashes.add(param_hash(space, canon))
            out.append(self._make_design(canon, h.generation, o, idx + (1 if h.generation == 0 else 0), parents, op,
                                         why, {}))
        return out

    def _repaired(self, raw: Dict[str, ParamValue], canon: Dict[str, ParamValue]) -> bool:
        for p in self.space.parameters:
            if p.kind == "continuous" and p.name in raw:
                try:
                    step = p.step or 0.1
                    if abs(float(raw[p.name]) - float(canon[p.name])) > step:
                        return True
                except (TypeError, ValueError):
                    return True
        return False

    def _make_design(self, params: Dict[str, ParamValue], gen: int, origin: str, idx: int, parents: List[str],
                     op: str, why: str, timings: Dict[str, float]) -> DesignResult:
        placeholder = Score(metrics={}, objective_scores={}, feasible=False, aggregate=-1e9)
        return DesignResult(design_id=make_design_id(self.run_id, gen, origin, idx), run_id=self.run_id,
                            generation=gen, origin=origin, params=params, param_hash=param_hash(self.space, params),  # type: ignore[arg-type]
                            parent_ids=parents, operator=op, rationale=why, score=placeholder, timings_ms=timings)

    def _evaluate_and_publish(self, batch: List[DesignResult], propose_ms: float) -> None:
        h = self.history
        t0 = time.perf_counter()
        scores = self.w.sim.evaluate_batch(self.space, [d.params for d in batch], self.goal)
        eval_ms = (time.perf_counter() - t0) * 1000.0 / max(1, len(batch))
        for d, s in zip(batch, scores):
            d.score = s
            d.timings_ms = {"propose": round(propose_ms, 1), "eval": round(eval_ms, 2)}
            h.add(d)
        try:
            ranks = self.w.sim.pareto_ranks([d.score for d in h.designs], self.goal)
            for d, r in zip(h.designs, ranks):
                d.pareto_rank = r
        except Exception as e:  # noqa: BLE001
            log.warning("pareto_ranks failed: %s", e)
        for d in batch:
            self.emit("design_evaluated", DesignEvaluated(design=d))
        self._update_champion()

    def _update_champion(self) -> None:
        h, cfg = self.history, self.config
        best = max(h.designs, key=lambda d: d.score.aggregate)
        prev = h.champion
        if prev is not None and best.design_id == prev.design_id:
            return
        delta = best.score.aggregate - prev.score.aggregate if prev else 0.0
        h.champion = best
        self.emit("champion_updated", ChampionUpdated(design_id=best.design_id,
                                                      previous_id=prev.design_id if prev else None,
                                                      aggregate=best.score.aggregate, delta=round(delta, 5),
                                                      reason=self._why_better(prev, best)))
        if cfg.profile != "bench" and (prev is None or delta >= cfg.geometry_min_improvement) \
                and self.builds < cfg.geometry_max_builds:
            self._enqueue_geometry(best)

    def _why_better(self, prev: Optional[DesignResult], best: DesignResult) -> str:
        if prev is None:
            return "first evaluated design"
        if best.score.feasible and not prev.score.feasible:
            return "first design to satisfy all hard constraints"
        deltas = sorted(((best.score.objective_scores.get(k, 0) - prev.score.objective_scores.get(k, 0), k)
                         for k in best.score.objective_scores), reverse=True)
        if not deltas:
            return "higher aggregate score"
        d, k = deltas[0]
        return "%s score %+.2f" % (k, d)

    def _after_generation(self, g: int, sens: Dict[str, Dict[str, float]], t0: float) -> None:
        h, cfg = self.history, self.config
        best = h.champion.score.aggregate if h.champion else -1e9
        prev_best = h.best_by_gen[-1] if h.best_by_gen else None
        h.stagnation = 0 if prev_best is None or best - prev_best >= cfg.min_improvement else h.stagnation + 1
        h.best_by_gen.append(best)
        evals = len(h.designs)
        self.curves["agent"].append(CurvePoint(evals=evals, best_aggregate=round(best, 5)))

        # critic: async on a snapshot so the loop never waits on it
        snap = copy.copy(h)
        snap.designs, snap.by_id, snap.insights = list(h.designs), dict(h.by_id), list(h.insights)
        fresh_sens = self._sensitivity() if h.champion is not None else sens
        self.critic_futures.append(self.pool.submit(self._critic, snap, fresh_sens, g))

        # strategist: LLM every 3rd generation or on stagnation, async (it never blocks a proposal);
        # its directive is adopted at the first generation boundary after it returns. Rules otherwise.
        old = h.directive
        d, res = strategist.rules_directive(h, self.N), None
        f = self.strategist_future
        if f is not None and f.done():
            self.strategist_future = None
            try:
                d, res = f.result()
            except Exception as e:  # noqa: BLE001
                log.warning("strategist failed: %s", e)
        if d.mode == "refine" or h.generations - g - 1 <= 2:
            d = strategist.rules_directive(h, self.N) if res is None else d
        h.directive = d
        if res is not None or d.mode != old.mode:
            self.message("strategist", "directive", "%s: %s" % (d.mode, d.reason),
                         body="n_explore=%d, step_scale=%.2f, focus=%s" % (d.n_explore, d.step_scale,
                                                                           ", ".join(d.focus_params) or "-"), res=res)
        if self.strategist_future is None and (g % 3 == 1 or h.stagnation >= 2) and g < cfg.generations - 2:
            self.strategist_future = self.pool.submit(strategist.strategize, snap, self.N, self.llm_budget)

        self._baseline_progress(evals)
        pareto_ids = [d.design_id for d in h.designs if d.pareto_rank == 0]
        gen = [d for d in h.designs if d.generation == g]
        self.emit("generation_complete", GenerationComplete(generation=Generation(
            run_id=self.run_id, index=g, design_ids=[d.design_id for d in gen],
            champion_id=h.champion.design_id if h.champion else "", best_aggregate=round(best, 5),
            mean_aggregate=round(sum(d.score.aggregate for d in gen) / max(1, len(gen)), 5),
            feasible_count=sum(1 for d in gen if d.score.feasible), evals_used=evals, evals_budget=self.budget_evals,
            directive=d, critic_summary=self.last_critic_why, elapsed_ms=round((time.perf_counter() - t0) * 1000, 1)),
            pareto_ids=pareto_ids))
        self.emit("budget_update", BudgetUpdate(budget=self.budget_status()))

    def _critic(self, snap: RunHistory, sens: Dict[str, Dict[str, float]], g: int) -> None:
        try:
            data, res, removed = critic.critique(snap, self.catalog, sens, budget=self.llm_budget)
            why = str(data.get("why_winner_won", ""))
            with self.lock:
                self.last_critic_why = why
                self.history.insights.extend(str(s) for s in data.get("insights", []))
            body = "\n".join("- " + str(s) for s in data.get("insights", []))
            if removed:
                body += "\n\n_Numeric-claim check removed unverified number(s): %s_" % ", ".join(removed)
            self.message("critic", "insight", why, body=body, refs=critic.champion_ids(snap), res=res, generation=g)
            for s in data.get("suspicious", [])[:2]:
                self.message("critic", "warning", "%s: %s" % (s.get("design_id", "?"), s.get("reason", "")),
                             refs=[s["design_id"]] if s.get("design_id") in snap.by_id else [], generation=g,
                             model=res.model if res else "rules")
        except Exception as e:  # noqa: BLE001 — the critic is advisory
            log.warning("critic failed: %s", e)

    # ------------------------------------------------------------ baselines / landscape / geometry

    def _baseline_progress(self, evals: int, wait: float = 15.0) -> None:
        for method in self.config.baselines:
            if method not in self.baseline_results and method in self.base_futures:
                try:
                    self.baseline_results[method] = self.base_futures[method].result(timeout=wait)
                except Exception as e:  # noqa: BLE001 — not done yet, or failed: skip this tick
                    log.info("%s baseline not ready: %s", method, e)
            hist = self.baseline_results.get(method)
            if hist is None:
                continue
            sub = hist[:max(1, min(evals, len(hist)))]
            best = max(sub, key=lambda d: d.score.aggregate)
            cp = CurvePoint(evals=len(sub), best_aggregate=round(best.score.aggregate, 5))
            self.curves.setdefault(method, []).append(cp)
            self.emit("baseline_progress", BaselineProgress(method=method, evals_used=len(sub),  # type: ignore[arg-type]
                                                           best_aggregate=best.score.aggregate, best=best,
                                                           curve_point=cp))

    def _landscape(self) -> None:
        try:
            metrics = [o.metric for o in self.goal.objectives][:2]
            # Fill to two axes from the domain pack's headline metrics, then the catalog.
            pack = getattr(self.w, "packs", {}).get(getattr(self.w, "space_project", {}).get(self.space.id, ""))
            for extra in list(getattr(pack, "headline_metrics", [])) + [m.name for m in self.catalog]:
                if len(metrics) < 2 and extra not in metrics:
                    metrics.append(extra)
            n = 2000 if self.config.profile == "full" else 1200
            pts = self.w.sim.landscape(self.space, self.goal, n=n, seed=self.config.seed)
            step = max(1, len(pts) // 2000)
            points = [[round(s.metrics[metrics[0]], 4), round(s.metrics[metrics[1]], 4), round(s.aggregate, 4),
                       s.feasible] for _, s in pts[::step]]
            self.emit("landscape_ready", LandscapeReady(metrics=metrics, points=points, n=len(points)))
        except Exception as e:  # noqa: BLE001
            log.warning("landscape failed: %s", e)

    def _enqueue_geometry(self, d: DesignResult, final: bool = False) -> None:
        if not final and self.builds >= self.config.geometry_max_builds:
            return
        self.builds += 1
        from shared.contracts import geometry_key
        d.geometry = GeometryRef(geometry_key=geometry_key(self.space, d.params), status="pending", source="none")
        self.geo_q.put(d)

    def _geometry_worker(self) -> None:
        while True:
            d = self.geo_q.get()
            if d is None:
                return
            try:
                ref = self.w.cad.build_geometry(self.space, d.params)
            except Exception as e:  # noqa: BLE001 — cad.build_geometry should never raise; be safe
                from shared.contracts import geometry_key
                ref = GeometryRef(geometry_key=geometry_key(self.space, d.params), status="failed", source="none",
                                  error="%s: %s" % (type(e).__name__, e))
            d.geometry = ref
            if ref.status == "skipped" and "onshape_cache_only" not in self.degradations:
                self.degradations.append("onshape_cache_only")
            if ref.status == "failed":
                self.error("onshape", ref.regen_status or "failed", "geometry for %s: %s" % (d.design_id, ref.error))
            self.emit("geometry_ready", GeometryReady(design_id=d.design_id, geometry=ref))
            self.emit("budget_update", BudgetUpdate(budget=self.budget_status()))
            self.geo_q.task_done()

    # ------------------------------------------------------------ finish

    def _finish(self, base_futures: Dict[str, Future]) -> None:
        h, cfg = self.history, self.config
        for m, f in base_futures.items():
            try:
                self.baseline_results[m] = f.result(timeout=120)
            except Exception as e:  # noqa: BLE001
                self.error("backend", "baseline_failed", "%s baseline: %s" % (m, e))
        # matched budget: baselines are judged at exactly the evaluations the agent used
        matched = len(h.designs)
        if self.baseline_results and (not self.curves.get(cfg.baselines[0]) or
                                      self.curves[cfg.baselines[0]][-1].evals != matched):
            self._baseline_progress(matched)
        for f in self.critic_futures + ([self.landscape_future] if self.landscape_future else []):
            try:
                f.result(timeout=40)
            except Exception:  # noqa: BLE001 — late or failed advisory work is dropped, never blocks forever
                pass
        champ = h.champion
        hifi = None
        if champ is not None and cfg.profile != "bench":
            try:
                hifi = self.w.sim.validate_high_fidelity(self.space, champ.params, self.goal)
            except Exception as e:  # noqa: BLE001
                self.error("sim", "hifi_failed", str(e))
            if champ.geometry is None:
                self._enqueue_geometry(champ, final=True)
            deadline = time.time() + 45
            while self.geo_q.unfinished_tasks and time.time() < deadline:
                time.sleep(0.1)
        baseline_best = {m: max(r[:matched], key=lambda d: d.score.aggregate)
                         for m, r in self.baseline_results.items() if r}
        if champ is not None and cfg.profile != "bench":
            rep, res = reporter.report(h, hifi, baseline_best, self.last_critic_why or "", budget=self.llm_budget)
            self.message("reporter", "report", rep.get("headline") or "Final report",
                         body=rep.get("narrative", "") + ("\n\n**Caveats:** " + "; ".join(rep["caveats"])
                                                          if rep.get("caveats") else ""),
                         refs=[champ.design_id], res=res)
        s = self.summary
        s.status = "stopped" if self.stop_flag.is_set() else "complete"
        s.finished_at = _now_iso()
        s.champion = champ
        s.baseline_best = baseline_best
        s.curves = self.curves
        s.pareto_ids = [d.design_id for d in h.designs if d.pareto_rank == 0]
        s.hifi_check = hifi
        s.budget = self.budget_status()
        s.degradations = self.degradations
        s.recording = self.ch.path.name if self.ch.path else None
        s.report_url = "/api/runs/%s/report" % self.run_id
        self.emit("run_complete", RunComplete(summary=s))

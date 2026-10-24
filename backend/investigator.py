"""The investigator: Darwin's hypothesis-driven design loop (PLAN.md Part B.3). Owner: W-C.

One step = one small experiment:
  plan (LLM: one hypothesis + predictions, validated by code; recorded before any simulation)
  -> run (solver, deterministic) -> score each prediction (code) -> analyze (LLM: explanation +
  lesson, numeric-claim checked) -> decide (code: accepted / rejected / pivot) -> apply the
  accepted design to Onshape (optional hook) -> learn (notebook).
The LLM never decides acceptance and never supplies a number in the evidence. With no LLM (or
over budget) a rules step runs instead, labeled "rules", so a session never dies.

Terminal use (CP-C):  python -m backend.investigator --project rear_wing [--steps 8] [--sims 20]
"""
import argparse
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.contracts import (
    AgentMessage, BudgetStatus, CurvePoint, DesignResult, DesignSpace, Goal, GeometryRef, ModelBudget,
    ParamValue, RunConfig, RunSummary, canonicalize, make_design_id, param_hash,
)
from shared.events import (
    AgentMessageEvent, BudgetUpdate, ChampionUpdated, DesignEvaluated, ErrorEvent, RunComplete, RunStarted,
)
from shared.investigation import (
    Belief, DesignApplied, Hypothesis, Notebook, Prediction, StepResult, score_prediction,
)

from backend import llm
from backend.agents.base import scrub_claims, system_prompt, user_message
from backend.agents.schemas import investigator_analyze_schema, investigator_plan_schema
from backend.bus import Channel

log = logging.getLogger("darwin.investigator")

ApplyHook = Callable[[DesignSpace, Dict[str, ParamValue]], GeometryRef]
VersionHook = Callable[[str], Optional[str]]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _pct(before: float, after: float) -> float:
    if abs(before) < 1e-9:
        return 0.0 if abs(after) < 1e-9 else (100.0 if after > 0 else -100.0)
    return 100.0 * (after - before) / abs(before)


def _clip(text: str, max_words: int) -> str:
    """Cap length without cutting mid-sentence: past the cap, end at the last full sentence."""
    words = text.split()
    if len(words) <= max_words:
        return " ".join(words)
    cut = " ".join(words[:max_words])
    end = max(cut.rfind(". "), cut.rfind("; "), cut.rfind("! "))
    return (cut[:end + 1] if end > 0 else cut.rstrip(",;:") + "...").strip()


def _violation(d: DesignResult) -> float:
    return sum(v.amount for v in d.score.violations if v.hard)


def better(a: DesignResult, b: DesignResult) -> bool:
    """Is design `a` an improvement over `b`? Feasibility first, then the goal's aggregate."""
    if a.score.feasible and not b.score.feasible:
        return True
    if a.score.feasible and b.score.feasible:
        return a.score.aggregate > b.score.aggregate + 1e-9
    if not a.score.feasible and not b.score.feasible:
        return _violation(a) < _violation(b) - 1e-9
    return False


class Investigator:
    def __init__(self, w: Any, channel: Channel, space: DesignSpace, goal: Goal, *, max_steps: int = 8,
                 max_sims: int = 20, start: Optional[Dict[str, ParamValue]] = None,
                 apply: Optional[ApplyHook] = None, version: Optional[VersionHook] = None,
                 pack: Any = None, llm_max_spend_usd: float = 0.60) -> None:
        self.w, self.ch, self.run_id = w, channel, channel.run_id
        self.space, self.goal = space, goal
        self.max_steps, self.max_sims = max_steps, max_sims
        self.apply, self.version, self.pack = apply, version, pack
        names = [p.name for p in space.parameters]
        self.editable = [n for n in (goal.editable or names) if n in names and n not in goal.fixed_params]
        self.fixed = [n for n in names if n not in self.editable]
        self.start_params = canonicalize(space, dict(start or {}, **goal.fixed_params))
        self.catalog = w.catalog(space.scorer)
        self.metric_names = [m.name for m in self.catalog]
        self.goal_metrics = list(dict.fromkeys([o.metric for o in goal.objectives] +
                                               [c.ref for c in goal.constraints if not c.ref.startswith("param:")]))
        self.principles = pack.principles() if pack is not None and hasattr(pack, "principles") else []
        self.notebook = Notebook()
        self.history = []  # type: List[Dict[str, Any]]
        self.designs = []  # type: List[DesignResult]
        self.hashes = set()  # type: set
        self.rejections = {}  # type: Dict[str, int]       # consecutive rejections per lever
        self.scores = []  # type: List[float]
        self.curve = []  # type: List[CurvePoint]
        self.llm_budget = llm.RunLLMBudget(max_calls=4 * max_steps, max_spend_usd=llm_max_spend_usd)
        self.degradations = []  # type: List[str]
        self.stop_flag = threading.Event()
        self.closed = False
        self.lock = threading.RLock()
        self.current = None  # type: Optional[DesignResult]
        self.seed = None  # type: Optional[DesignResult]
        self.summary = RunSummary(run_id=self.run_id, status="running", goal=goal, design_space_id=space.id,
                                  config=RunConfig(eval_budget=max_sims, baselines=[]), started_at=_now_iso())
        self.thread = threading.Thread(target=self._main, name="inv-%s" % self.run_id, daemon=True)

    # ------------------------------------------------------------ plumbing

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()

    def emit(self, type_: str, payload: Any) -> None:
        with self.lock:
            if self.closed:
                return
            if type_ == "run_complete":
                self.closed = True
            self.ch.emit(type_, payload)

    def message(self, summary: str, kind: str = "status", model: str = "rules") -> None:
        self.emit("agent_message", AgentMessageEvent(message=AgentMessage(
            message_id="%s-m%d" % (self.run_id, len(self.ch.events)), run_id=self.run_id,
            generation=len(self.history), agent="system", kind=kind, model=model, summary=summary[:300])))  # type: ignore[arg-type]

    def budget_status(self) -> BudgetStatus:
        try:
            onshape = self.w.cad.budget_status()
        except Exception:  # noqa: BLE001 — budget display must never kill a session
            from shared.contracts import OnshapeBudget
            onshape = OnshapeBudget(account_label="unknown", calls_session=0, calls_ledger_total=0,
                                    remaining_estimate=0, reserve=0, reserve_unlocked=False, hard_stop=True)
        return BudgetStatus(
            onshape=onshape,
            model=ModelBudget(provider=llm.provider_name(), calls_run=self.llm_budget.calls,
                              calls_cap_run=self.llm_budget.max_calls,
                              spend_run_usd=round(self.llm_budget.spend_usd, 5),
                              spend_cap_run_usd=self.llm_budget.max_spend_usd,
                              spend_total_usd=round(llm.SpendLedger.read()["total_usd"], 5),
                              spend_cap_total_usd=llm.SpendLedger.cap()),
            evals_used=len(self.designs), evals_budget=self.max_sims)

    def _evaluate(self, params: Dict[str, ParamValue], step: int, origin: str, idx: int, op: str, why: str,
                  parents: List[str]) -> DesignResult:
        p = canonicalize(self.space, params)
        t0 = time.perf_counter()
        score = self.w.sim.evaluate(self.space, p, self.goal)
        d = DesignResult(design_id=make_design_id(self.run_id, step, origin, idx), run_id=self.run_id,
                         generation=step, origin=origin, params=p, param_hash=param_hash(self.space, p),  # type: ignore[arg-type]
                         parent_ids=parents, operator=op, rationale=why[:200], score=score,
                         timings_ms={"eval": round((time.perf_counter() - t0) * 1000.0, 3)})
        self.designs.append(d)
        self.hashes.add(d.param_hash)
        self.emit("design_evaluated", DesignEvaluated(design=d))
        return d

    # ------------------------------------------------------------ the loop

    def _main(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — always end the stream cleanly
            log.exception("investigation %s crashed", self.run_id)
            self.emit("error", ErrorEvent(component="backend", code="crash", message=("%s: %s" % (
                type(e).__name__, e))[:300], recoverable=False))
            self.summary.status = "failed"
            self._finish(reason="crashed")

    def _run(self) -> None:
        self.emit("run_started", RunStarted(summary=self.summary, design_space=self.w.public_space(self.space),
                                            metric_catalog=self.catalog))
        self.seed = self.current = self._evaluate(self.start_params, 0, "seed", 0, "seed",
                                                  "The design as it is in Onshape now.", [])
        self.curve.append(CurvePoint(evals=1, best_aggregate=self.current.score.aggregate))
        if self.version is not None:
            self._version("Before Darwin")
        reason = "step budget spent"
        for step in range(1, self.max_steps + 1):
            if self.stop_flag.is_set():
                reason = "stopped by the user"
                break
            left = self.max_sims - len(self.designs)
            if left <= 0:
                reason = "simulation budget spent"
                break
            if len(self.notebook.ruled_out) >= len(self.editable):
                reason = "every editable lever is ruled out"
                break
            hyp, stop_reason = self._plan(step, left)
            if hyp is None:
                reason = stop_reason or "no promising lever left"
                break
            self._step(step, hyp)
        self._finish(reason=reason)

    def _step(self, step: int, hyp: Hypothesis) -> None:
        self.emit("step_planned", hyp)                          # predictions recorded before any simulation
        origin = "agent" if hyp.source == "llm" else "fallback"
        tested = [self._evaluate(c, step, origin, i, "refine", hyp.rationale, [self.current.design_id])
                  for i, c in enumerate(hyp.candidates)]
        improving = [d for d in tested if better(d, self.current)]
        best = max(improving, key=lambda d: d.score.aggregate) if improving else \
            min(tested, key=lambda d: (_violation(d), -d.score.aggregate))
        before = self.current
        deltas = {m: round(_pct(before.score.metrics[m], best.score.metrics[m]), 3)
                  for m in self.metric_names if m in before.score.metrics and m in best.score.metrics}
        checks = [score_prediction(p, deltas.get(p.metric, 0.0)) for p in hyp.predictions]
        self.scores += [c.score for c in checks]
        if improving:
            verdict = "accepted"
            for lever in hyp.levers:                            # rule-outs count consecutive rejections
                self.rejections[lever] = 0
        else:
            for lever in hyp.levers:
                self.rejections[lever] = self.rejections.get(lever, 0) + 1
            verdict = "pivot" if any(self.rejections[lv] >= 2 for lv in hyp.levers) else "rejected"
        explanation, lesson = self._analyze(step, hyp, before, best, deltas, checks, verdict)
        if verdict == "accepted":
            self.current = best
            self.emit("champion_updated", ChampionUpdated(
                design_id=best.design_id, previous_id=before.design_id, aggregate=best.score.aggregate,
                delta=best.score.aggregate - before.score.aggregate, reason="step %d accepted" % step))
            self._apply(best)
        self.emit("step_result", StepResult(step=step, tested=[d.design_id for d in tested], best_id=best.design_id,
                                            deltas=deltas, checks=checks, verdict=verdict,  # type: ignore[arg-type]
                                            explanation=explanation, lesson=lesson))
        self._learn(step, hyp, before, best, deltas, verdict, lesson)
        self.history.append({"step": step, "levers": hyp.levers, "verdict": verdict, "lesson": lesson,
                             "candidates_tried": [{k: d.params[k] for k in hyp.levers} for d in tested],
                             "deltas": {m: deltas[m] for m in self.goal_metrics if m in deltas}})
        self.curve.append(CurvePoint(evals=len(self.designs), best_aggregate=self.current.score.aggregate))
        self.emit("budget_update", BudgetUpdate(budget=self.budget_status()))

    def _learn(self, step: int, hyp: Hypothesis, before: DesignResult, best: DesignResult,
               deltas: Dict[str, float], verdict: str, lesson: str) -> None:
        nb = self.notebook
        for lever in hyp.levers:
            moved = float(best.params[lever]) - float(before.params[lever])
            if abs(moved) > 1e-12 and len(hyp.levers) == 1:     # only single-lever steps give clean effects
                nb.lever_effects.setdefault(lever, {}).update(
                    {m: round(deltas[m] / moved, 4) for m in self.goal_metrics if m in deltas})
            if verdict == "pivot" and self.rejections.get(lever, 0) >= 2 and lever not in nb.ruled_out:
                nb.ruled_out.append(lever)
        if lesson:
            nb.beliefs.append(Belief(text=lesson, evidence_steps=[step],
                                     principle_id=hyp.principle_ids[0] if hyp.principle_ids else None))
        nb.accuracy.append(round(sum(self.scores) / len(self.scores), 3) if self.scores else 0.0)
        self.emit("notebook_updated", nb.model_copy(deep=True))

    # ------------------------------------------------------------ CAD hooks

    def _apply(self, d: DesignResult) -> None:
        if self.apply is None:
            return
        try:
            ref = self.apply(self.space, d.params)
            self.emit("design_applied", DesignApplied(design_id=d.design_id, geometry=ref))
            if ref.status != "ready":
                self.degradations.append("onshape_write_failed@%s" % d.design_id)
                self.message("Onshape write did not complete (%s); continuing in simulation only."
                             % (ref.error or ref.status), kind="warning")
        except Exception as e:  # noqa: BLE001 — a CAD failure never ends the session
            log.warning("apply failed: %s", e)
            self.degradations.append("onshape_write_failed@%s" % d.design_id)
            self.message("Onshape write failed: %s" % str(e)[:150], kind="warning")

    def _version(self, name: str) -> None:
        try:
            ref = self.version(name) if self.version else None
            if ref is not None and self.current is not None:
                self.emit("design_applied", DesignApplied(
                    design_id=self.current.design_id, version=name,
                    geometry=GeometryRef(geometry_key=self.current.param_hash, status="ready", source="none")))
        except Exception as e:  # noqa: BLE001
            log.warning("version failed: %s", e)
            self.degradations.append("onshape_version_failed")

    # ------------------------------------------------------------ plan

    def _plan_block(self, step: int, sims_left: int) -> Dict[str, Any]:
        cur = self.current
        specs = {p.name: p for p in self.space.parameters}
        binding = None
        info = {m.name: m for m in self.catalog}
        for c in self.goal.constraints:
            if c.ref.startswith("param:") or c.ref not in cur.score.metrics:
                continue
            actual = cur.score.metrics[c.ref]
            slack = (c.value - actual) if c.op == "<=" else (actual - c.value)
            span = max(info[c.ref].typical_max - info[c.ref].typical_min, 1e-9) if c.ref in info else 1.0
            if binding is None or slack / span < binding["slack_frac"]:
                binding = {"metric": c.ref, "limit": c.value, "actual": round(actual, 4),
                           "slack": round(slack, 4), "slack_frac": round(slack / span, 4)}
        return {
            "step": step,
            "goal": {"text": self.goal.source_text,
                     "objectives": [o.model_dump(mode="json") for o in self.goal.objectives],
                     "constraints": [c.model_dump(mode="json") for c in self.goal.constraints]},
            "editable": [{"name": n, "unit": specs[n].unit, "min": specs[n].min, "max": specs[n].max,
                          "current": cur.params[n], "description": specs[n].description} for n in self.editable],
            "fixed": {n: cur.params[n] for n in self.fixed},
            "current": {"metrics": cur.score.metrics, "feasible": cur.score.feasible,
                        "violations": [{"ref": v.ref, "limit": v.limit, "actual": v.actual}
                                       for v in cur.score.violations],
                        "binding_constraint": binding},
            "metrics": [{"name": m.name, "unit": m.unit, "description": m.description} for m in self.catalog],
            "principles": [{k: p[k] for k in ("id", "statement", "effects", "levers")} for p in self.principles],
            "notebook": {"beliefs": [b.text for b in self.notebook.beliefs[-8:]],
                         "lever_effects_pct_per_unit": self.notebook.lever_effects,
                         "ruled_out": self.notebook.ruled_out, "prediction_accuracy": self.notebook.accuracy[-3:]},
            "last_steps": self.history[-4:],
            "budget": {"simulations_left": sims_left, "steps_left": self.max_steps - step + 1},
        }

    def _validate_plan(self, data: Dict[str, Any], step: int, sims_left: int) -> Tuple[Optional[Hypothesis], str]:
        """Raise ValueError (fed back to the model) for anything unusable. Returns (hypothesis, stop_reason)."""
        if data.get("stop"):
            if step <= 2 and len(self.notebook.ruled_out) < len(self.editable):
                raise ValueError("too early to stop: run at least two experiments first")
            return None, str(data.get("stop_reason") or "no promising lever left")[:200]
        levers = list(dict.fromkeys(data.get("levers") or []))
        if not 1 <= len(levers) <= 2:
            raise ValueError("choose 1 or 2 levers")
        for lv in levers:
            if lv not in self.editable:
                raise ValueError("%s is not editable (editable: %s)" % (lv, ", ".join(self.editable)))
            if lv in self.notebook.ruled_out:
                raise ValueError("%s is ruled out by the notebook" % lv)
        specs = {p.name: p for p in self.space.parameters}
        cands, seen = [], set()
        for c in (data.get("candidates") or [])[:4]:
            values = dict(self.current.params)
            for s in c.get("settings") or []:
                name, value = s.get("param"), s.get("value")
                if name not in levers:
                    raise ValueError("candidate changes %s, which is not one of the levers %s" % (name, levers))
                p = specs[name]
                v = float(value)
                if (p.min is not None and v < p.min - 1e-9) or (p.max is not None and v > p.max + 1e-9):
                    raise ValueError("%s=%s is outside [%s, %s]" % (name, value, p.min, p.max))
                values[name] = v
            canon = canonicalize(self.space, values)
            h = param_hash(self.space, canon)
            if h in self.hashes or h in seen:
                continue
            seen.add(h)
            cands.append(canon)
        if not cands:
            raise ValueError("every candidate was already simulated or equals the current design; propose new values")
        cands = cands[:max(1, sims_left)]
        known = {p["id"] for p in self.principles}
        pids = [pid for pid in data.get("principle_ids") or [] if pid in known]
        preds = []
        for pr in (data.get("predictions") or [])[:6]:
            if pr.get("metric") not in self.metric_names:
                raise ValueError("unknown metric %r" % pr.get("metric"))
            lo, hi = sorted((float(pr["pct_low"]), float(pr["pct_high"])))
            # "down 16-50%" written as [16, 50]: the direction disambiguates, so normalize the sign.
            if pr["direction"] == "down" and lo > 0:
                lo, hi = -hi, -lo
            elif pr["direction"] == "up" and hi < 0:
                lo, hi = -hi, -lo
            if (pr["direction"] == "up" and hi <= 0) or (pr["direction"] == "down" and lo >= 0):
                raise ValueError("prediction for %s: direction %s contradicts range [%s, %s]"
                                 % (pr["metric"], pr["direction"], lo, hi))
            preds.append(Prediction(metric=pr["metric"], direction=pr["direction"], pct_low=lo, pct_high=hi))
        objective = [o.metric for o in self.goal.objectives]
        if not any(p.metric in objective for p in preds):
            raise ValueError("predict the goal metric(s) %s" % ", ".join(objective))
        rationale, _ = scrub_claims(_clip(str(data.get("rationale", "")), 55), self._plan_block(step, sims_left))
        return Hypothesis(step=step, levers=levers, candidates=cands, principle_ids=pids, rationale=rationale,
                          predictions=preds, source="llm"), ""

    def _plan(self, step: int, sims_left: int) -> Tuple[Optional[Hypothesis], str]:
        block = self._plan_block(step, sims_left)
        out = {}  # type: Dict[str, Any]
        schema = investigator_plan_schema(self.editable, self.metric_names, [p["id"] for p in self.principles])
        try:
            res = llm.call_model("investigator_plan", system_prompt("investigator_plan", self.space),
                                 user_message("Propose the next experiment.", block), schema,
                                 model=llm.deep_model() if llm.provider_name() == "anthropic" else None,
                                 max_tokens=1500, effort="medium", budget=self.llm_budget,
                                 validate=lambda d: out.update(r=self._validate_plan(d, step, sims_left)))
            return out["r"] if "r" in out else self._validate_plan(res.data, step, sims_left)
        except (llm.LLMUnavailable, llm.BudgetExceeded) as e:
            self.degradations.append("rules@step%d" % step)
            self.message("Planner unavailable (%s); using a rules step." % str(e)[:120], kind="warning")
            return self._rules_plan(step, sims_left)

    def _rules_plan(self, step: int, sims_left: int) -> Tuple[Optional[Hypothesis], str]:
        """One-factor sweep: an untried lever first, else the best measured one (PLAN.md B.3 fallback)."""
        objective = self.goal.objectives[0].metric
        tried = {lv for h in self.history for lv in h["levers"]}
        open_levers = [lv for lv in self.editable if lv not in self.notebook.ruled_out]
        if not open_levers:
            return None, "every editable lever is ruled out"
        untried = [lv for lv in open_levers if lv not in tried]
        effects = self.notebook.lever_effects
        lever = untried[0] if untried else max(open_levers, key=lambda lv: abs(effects.get(lv, {}).get(objective, 0)))
        spec = next(p for p in self.space.parameters if p.name == lever)
        sign = 1.0
        eff = effects.get(lever, {}).get(objective)
        if eff is not None and (eff < 0) == (self.goal.objectives[0].direction != "minimize"):
            sign = -1.0
        span = float(spec.max - spec.min) if spec.max is not None and spec.min is not None else 1.0
        cands, seen = [], set()
        for frac in (0.1, 0.2):
            values = dict(self.current.params, **{lever: float(self.current.params[lever]) + sign * frac * span})
            canon = canonicalize(self.space, values)
            h = param_hash(self.space, canon)
            if h not in self.hashes and h not in seen:
                seen.add(h)
                cands.append(canon)
        if not cands:
            if lever not in self.notebook.ruled_out:
                self.notebook.ruled_out.append(lever)
            return (self._rules_plan(step, sims_left) if len(self.notebook.ruled_out) < len(self.editable)
                    else (None, "no untested values left"))
        direction = "up" if self.goal.objectives[0].direction != "minimize" else "down"
        lo, hi = (0.0, 20.0) if direction == "up" else (-20.0, 0.0)
        return Hypothesis(step=step, levers=[lever], candidates=cands[:max(1, sims_left)], principle_ids=[],
                          rationale="Rules step: sweep %s %s by 10%% and 20%% of its range." %
                                    (lever, "up" if sign > 0 else "down"),
                          predictions=[Prediction(metric=objective, direction=direction, pct_low=lo, pct_high=hi)],
                          source="rules"), ""

    # ------------------------------------------------------------ analyze

    def _analyze(self, step: int, hyp: Hypothesis, before: DesignResult, best: DesignResult,
                 deltas: Dict[str, float], checks: List[Any], verdict: str) -> Tuple[str, str]:
        block = {"hypothesis": {"levers": hyp.levers, "rationale": hyp.rationale,
                                "principle_ids": hyp.principle_ids},
                 "changed": {lv: {"from": before.params[lv], "to": best.params[lv]} for lv in hyp.levers},
                 "before": before.score.metrics, "after": best.score.metrics,
                 "pct_change": deltas,
                 "predictions": [c.model_dump(mode="json") for c in checks],
                 "after_feasible": best.score.feasible,
                 "after_violations": [{"ref": v.ref, "limit": v.limit, "actual": v.actual}
                                      for v in best.score.violations],
                 "verdict": verdict}
        if hyp.source == "llm":
            try:
                res = llm.call_model("investigator_analyze", system_prompt("investigator_analyze", self.space),
                                     user_message("Explain this experiment.", block),
                                     investigator_analyze_schema(),
                                     model=llm.deep_model() if llm.provider_name() == "anthropic" else None,
                                     max_tokens=600, budget=self.llm_budget)
                expl, _ = scrub_claims(_clip(str(res.data.get("explanation", "")), 80), block)
                lesson, _ = scrub_claims(_clip(str(res.data.get("lesson", "")), 30), block)
                if expl:
                    return expl, lesson
            except (llm.LLMUnavailable, llm.BudgetExceeded) as e:
                self.degradations.append("rules_analysis@step%d" % step)
                log.info("analyze unavailable: %s", e)
        return self._rules_analysis(hyp, best, deltas, verdict)

    def _rules_analysis(self, hyp: Hypothesis, best: DesignResult, deltas: Dict[str, float],
                        verdict: str) -> Tuple[str, str]:
        parts = ["%s %+.1f%%" % (m, deltas[m]) for m in self.goal_metrics if m in deltas]
        why = "" if best.score.feasible else " (violates %s)" % ", ".join(v.ref for v in best.score.violations)
        lever = ", ".join(hyp.levers)
        expl = "Changing %s: %s%s. Verdict: %s." % (lever, "; ".join(parts), why, verdict)
        obj = self.goal.objectives[0].metric
        lesson = "%s %s %s under these limits." % (lever, "helps" if verdict == "accepted" else "does not improve",
                                                   obj)
        return expl, lesson

    # ------------------------------------------------------------ finish

    def _finish(self, reason: str) -> None:
        if self.summary.status == "running":
            self.summary.status = "stopped" if reason == "stopped by the user" else "complete"
        self.message("Stopping: %s." % reason)
        if self.version is not None and self.current is not None and self.seed is not None:
            obj = self.goal.objectives[0].metric if self.goal.objectives else None
            gain = _pct(self.seed.score.metrics.get(obj, 0.0), self.current.score.metrics.get(obj, 0.0)) if obj else 0
            self._version("Darwin: %s %+.0f%%" % (obj or "result", gain))
        self.summary.finished_at = _now_iso()
        self.summary.champion = self.current
        self.summary.seed_design = self.seed
        self.summary.curves = {"agent": self.curve}
        self.summary.budget = self.budget_status()
        self.summary.degradations = self.degradations
        self.emit("run_complete", RunComplete(summary=self.summary))


# ------------------------------------------------------------------ terminal

def _print_event(ev: Dict[str, Any]) -> None:
    t, p = ev["type"], ev["payload"]
    if t == "step_planned":
        preds = ", ".join("%s %s %g..%g%%" % (x["metric"], x["direction"], x["pct_low"], x["pct_high"])
                          for x in p["predictions"])
        print("\nSTEP %d [%s] levers %s  principles %s\n  why: %s\n  predict: %s\n  candidates: %s" % (
            p["step"], p["source"], p["levers"], p["principle_ids"] or "exploratory", p["rationale"], preds,
            [{k: c[k] for k in p["levers"]} for c in p["candidates"]]))
    elif t == "step_result":
        checks = ", ".join("%s %+.1f%% (%s)" % (c["metric"], c["actual_pct"], c["score"]) for c in p["checks"])
        print("  -> %s | %s\n  explain: %s\n  lesson: %s" % (p["verdict"].upper(), checks, p["explanation"],
                                                            p["lesson"]))
    elif t == "notebook_updated":
        print("  accuracy so far: %s" % p["accuracy"][-1:])
    elif t == "agent_message":
        print("  [%s] %s" % (p["message"]["kind"], p["message"]["summary"]))
    elif t == "run_complete":
        s = p["summary"]
        seed, champ = s["seed_design"]["score"]["metrics"], s["champion"]["score"]["metrics"]
        print("\nDONE (%s). Start -> final:" % s["status"])
        for k in seed:
            print("  %-20s %10.3f -> %10.3f" % (k, seed[k], champ[k]))
        print("  params:", s["champion"]["params"])


def main() -> None:
    import json
    from pathlib import Path
    from backend.bus import Bus
    from backend.wiring import Wiring
    ap = argparse.ArgumentParser(description="Run one investigation in the terminal (no CAD writes).")
    ap.add_argument("--project", default="rear_wing")
    ap.add_argument("--goal", default=str(Path(__file__).resolve().parent.parent / "shared" / "fixtures" / "v2"
                                          / "goal_wing.json"), help="Goal JSON file")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--sims", type=int, default=20)
    args = ap.parse_args()
    w, bus = Wiring(), Bus()
    space = w.resolve(args.project)
    goal = Goal.model_validate_json(Path(args.goal).read_text())
    ch = bus.open("session_%s" % time.strftime("%H%M%S"))
    inv = Investigator(w, ch, space, goal, max_steps=args.steps, max_sims=args.sims,
                       pack=w.packs.get(w.space_project.get(space.id, "")))
    print("modes:", w.modes, "| editable:", inv.editable, "| fixed:", inv.fixed,
          "| principles:", len(inv.principles))
    inv.start()
    shown = 0
    while inv.thread.is_alive() or shown < len(ch.events):
        while shown < len(ch.events):
            _print_event(ch.events[shown])
            shown += 1
        time.sleep(0.05)
    print("\nrecording:", ch.path)


if __name__ == "__main__":
    main()

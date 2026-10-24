import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { InspectResponse, StartSessionResponse } from '@shared/investigation';
import { api } from '@/lib/api';
import {
  parseJsonl,
  selectActiveRun,
  useDashboardStore,
  wsSource,
  type EventSource,
} from '@/store';
import type { RunFoldState } from '@/store/reducer';

const DEFAULT_PROMPT = 'More downforce without going over 15 N of drag at 25 m/s. You can change the angle, span, flap and endplates. Keep the chord.';

function label(value: string) {
  return value.replace(/_(deg|mm|frac|n)$/, '').replaceAll('_', ' ');
}

function metricLabel(value: string) {
  const names: Record<string, string> = {
    downforce_n: 'Downforce', drag_n: 'Drag', l_over_d: 'L/D', drag_induced_n: 'Induced drag',
    drag_profile_n: 'Profile drag', stall_margin_deg: 'Stall margin', span_efficiency: 'Span efficiency',
  };
  return names[value] ?? label(value);
}

function signed(value: number) {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function AccuracySparkline({ values }: { values: number[] }) {
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 50 : (index / (values.length - 1)) * 100;
    return `${x},${38 - value * 32}`;
  }).join(' ');
  const latest = values.at(-1);
  return (
    <div className="panel-accuracy" aria-label={`Prediction accuracy ${latest === undefined ? 'not available' : `${Math.round(latest * 100)} percent`}`}>
      <div><span>Prediction accuracy</span><strong>{latest === undefined ? '—' : `${Math.round(latest * 100)}%`}</strong></div>
      <svg viewBox="0 0 100 42" preserveAspectRatio="none" role="img" aria-label="Prediction accuracy by step">
        <path d="M0 38H100" className="spark-grid" />
        {points ? <polyline points={points} className="spark-line" /> : null}
        {values.map((value, index) => <circle key={index} cx={values.length === 1 ? 50 : (index / (values.length - 1)) * 100} cy={38 - value * 32} r="1.8" />)}
      </svg>
      <div className="spark-labels"><span>Step 1</span><span>{values.length ? `Step ${values.length}` : 'Waiting'}</span></div>
    </div>
  );
}

function StepCard({ run, step }: { run: RunFoldState; step: number }) {
  const plan = run.hypotheses.find((item) => item.step === step);
  const result = run.stepResults.find((item) => item.step === step);
  if (!plan) return null;
  const best = result ? run.designsById[result.best_id] : null;
  return (
    <article className={`step-card ${result ? `step-${result.verdict}` : 'step-running'}`}>
      <div className="step-rail"><span>{step}</span><i /></div>
      <div className="step-body">
        <header>
          <div><span className="step-kicker">Hypothesis {step}</span><h2>{plan.levers.map(label).join(' + ')}</h2></div>
          <span className={`verdict verdict-${result?.verdict ?? 'testing'}`}>{result?.verdict ?? 'testing'}</span>
        </header>
        <p className="hypothesis">{plan.rationale}</p>
        <div className="principles">
          {(plan.principle_ids.length ? plan.principle_ids : ['Exploratory']).map((id) => <span key={id}>{id}</span>)}
          {plan.source === 'rules' ? <span>rules fallback</span> : null}
        </div>
        <div className="prediction-table">
          <div className="prediction-heading"><span>Prediction</span><span>Actual</span></div>
          {plan.predictions.map((prediction) => {
            const check = result?.checks.find((item) => item.metric === prediction.metric);
            return (
              <div className="prediction-row" key={prediction.metric}>
                <span className="metric-name">{metricLabel(prediction.metric)}</span>
                <span className="predicted">{prediction.direction === 'up' ? '↑' : prediction.direction === 'down' ? '↓' : '→'} {signed(prediction.pct_low)} to {signed(prediction.pct_high)}</span>
                <span className={check ? check.in_range ? 'actual accurate' : check.direction_ok ? 'actual close' : 'actual miss' : 'actual'}>{check ? signed(check.actual_pct) : 'running…'}</span>
              </div>
            );
          })}
        </div>
        {best && result ? <div className="result-strip"><span>{best.params[plan.levers[0]]} {run.designSpace?.parameters.find((item) => item.name === plan.levers[0])?.unit}</span><span>{best.score.metrics.downforce_n?.toFixed(1)} N downforce</span><span>{best.score.metrics.drag_n?.toFixed(1)} N drag</span></div> : null}
        {result ? <>
          <details className="explanation"><summary>Why this happened</summary><p>{result.explanation}</p></details>
          <div className="lesson"><span>Learned</span>{result.lesson}</div>
        </> : <div className="simulating"><i />Testing {plan.candidates.length} design{plan.candidates.length === 1 ? '' : 's'}…</div>}
      </div>
    </article>
  );
}

function NotebookDrawer({ run }: { run: RunFoldState }) {
  const notebook = run.notebook;
  return (
    <details className="notebook-drawer">
      <summary><span><b>Lab notebook</b><small>{notebook.beliefs.length} beliefs · {notebook.ruled_out.length} ruled out</small></span><span>Open</span></summary>
      <div className="notebook-content">
        <section><h3>Beliefs</h3>{notebook.beliefs.length ? notebook.beliefs.map((belief, index) => <p key={`${index}-${belief.text}`}><b>{belief.evidence_steps.join(', ')}</b>{belief.text}</p>) : <em>No observations yet.</em>}</section>
        <section><h3>Measured lever effects</h3>{Object.entries(notebook.lever_effects).map(([lever, effects]) => <div className="lever-effect" key={lever}><b>{label(lever)}</b><span>{Object.entries(effects).map(([metric, value]) => `${metricLabel(metric)} ${value > 0 ? '+' : ''}${value.toFixed(2)}`).join(' · ')}</span></div>)}</section>
        {notebook.ruled_out.length ? <section><h3>Ruled out</h3>{notebook.ruled_out.map((item) => <p key={item}>× {item}</p>)}</section> : null}
      </div>
    </details>
  );
}

function FinalSummary({ run }: { run: RunFoldState }) {
  const before = run.seedDesign;
  const after = run.champion;
  if (!before || !after || run.status === 'running' || run.status === 'pending') return null;
  const downforce = ((after.score.metrics.downforce_n / before.score.metrics.downforce_n) - 1) * 100;
  const drag = ((after.score.metrics.drag_n / before.score.metrics.drag_n) - 1) * 100;
  const finalVersion = [...run.appliedDesigns].reverse().find((item) => Boolean(item.version))?.version;
  return (
    <section className="final-summary">
      <div className="final-check">✓</div><div className="step-kicker">Investigation complete</div>
      <h2>{signed(downforce)} downforce</h2><p>while drag changed {signed(drag)}</p>
      <div className="before-after">
        <div><span>Before</span><strong>{before.score.metrics.downforce_n.toFixed(1)} N</strong><small>{before.score.metrics.drag_n.toFixed(1)} N drag</small></div>
        <i>→</i>
        <div><span>After</span><strong>{after.score.metrics.downforce_n.toFixed(1)} N</strong><small>{after.score.metrics.drag_n.toFixed(1)} N drag</small></div>
      </div>
      {finalVersion ? <div className="version-chip">Onshape version · {finalVersion}</div> : null}
    </section>
  );
}

export default function PanelApp() {
  const query = useMemo(() => new URLSearchParams(window.location.search), []);
  const explicitDoc = query.get('doc');
  const docUrl = explicitDoc ?? 'mock://rear-wing';
  const initialRunId = query.get('session') ?? query.get('run_id') ?? (!explicitDoc ? 'session_fixture_wing' : null);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [inspection, setInspection] = useState<InspectResponse | null>(null);
  const [sessionScope, setSessionScope] = useState<Pick<StartSessionResponse, 'editable' | 'fixed'> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const activeRun = useDashboardStore(selectActiveRun);
  const sourceStatus = useDashboardStore((state) => state.sourceStatus);
  const reset = useDashboardStore((state) => state.reset);
  const ingest = useDashboardStore((state) => state.ingest);
  const ingestMany = useDashboardStore((state) => state.ingestMany);
  const setActiveRun = useDashboardStore((state) => state.setActiveRun);
  const setSourceStatus = useDashboardStore((state) => state.setSourceStatus);

  const subscribe = useCallback((source: EventSource) => {
    unsubscribeRef.current?.();
    reset();
    let firstRunId: string | null = null;
    unsubscribeRef.current = source.subscribe({
      status: setSourceStatus,
      next: (event) => {
        ingest(event);
        if (!firstRunId) { firstRunId = event.run_id; setActiveRun(event.run_id); }
      },
      error: (reason) => setError(reason.message),
      complete: () => setSourceStatus('complete'),
    });
  }, [ingest, reset, setActiveRun, setSourceStatus]);

  useEffect(() => {
    let cancelled = false;
    const initialize = async () => {
      const tasks: Promise<void>[] = [api.inspect(docUrl).then((value) => { if (!cancelled) setInspection(value); })];
      if (initialRunId) tasks.push(api.events(initialRunId).then((jsonl) => {
        if (cancelled) return;
        const events = parseJsonl(jsonl);
        reset(); ingestMany(events);
        if (events[0]) setActiveRun(events[0].run_id);
        setSourceStatus('complete');
      }));
      const results = await Promise.allSettled(tasks);
      const failed = results.find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failed && !cancelled) setError(failed.reason instanceof Error ? failed.reason.message : String(failed.reason));
    };
    void initialize();
    return () => { cancelled = true; unsubscribeRef.current?.(); };
  }, [docUrl, ingestMany, initialRunId, reset, setActiveRun, setSourceStatus]);

  const editable = sessionScope?.editable ?? activeRun?.summary?.goal.editable ?? [];
  const fixed = sessionScope?.fixed ?? inspection?.params.filter((param) => !editable.includes(param.name)).map((param) => param.name) ?? [];
  const steps = activeRun?.hypotheses.map((item) => item.step) ?? [];
  const running = activeRun?.status === 'running';

  const start = async () => {
    setBusy(true); setError(null);
    try {
      const session = await api.startSession({ doc_url: docUrl, prompt, max_sims: 20, max_steps: 8 });
      setSessionScope(session);
      subscribe(wsSource(session.run_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally { setBusy(false); }
  };

  const stop = async () => {
    if (!activeRun) return;
    setBusy(true);
    try { await api.stopSession(activeRun.runId); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  return (
    <div className="panel-app">
      <header className="panel-header"><div className="darwin-glyph">D</div><div><strong>DARWIN</strong><span>Aerodynamic reasoning agent</span></div><div className={`panel-status status-${running ? 'live' : 'ready'}`}><i />{running ? sourceStatus : activeRun ? 'complete' : 'ready'}</div></header>
      <main>
        <section className="prompt-card">
          <label htmlFor="design-goal">What should I improve?</label>
          <textarea id="design-goal" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} disabled={running} />
          <div className="scope-block"><span>Will change</span><div>{editable.map((item) => <b key={item}>{label(item)}</b>)}</div></div>
          <div className="scope-block keep"><span>Will keep</span><div>{fixed.map((item) => <b key={item}>{label(item)}</b>)}<b>mounts</b><b>airfoil</b></div></div>
          {running ? <button className="panel-button stop" type="button" onClick={() => void stop()} disabled={busy}>Stop after this step</button> : <button className="panel-button" type="button" onClick={() => void start()} disabled={busy || !prompt.trim()}>{busy ? 'Starting…' : activeRun ? 'Run again' : 'Start investigation'}</button>}
        </section>

        {error ? <div className="panel-error" role="alert">{error}</div> : null}
        {activeRun ? <>
          <AccuracySparkline values={activeRun.notebook.accuracy} />
          <section className="timeline" aria-label="Investigation steps">
            {steps.map((step) => <StepCard key={step} run={activeRun} step={step} />)}
            {!steps.length ? <div className="panel-empty">Reading the model and establishing a baseline…</div> : null}
          </section>
          <FinalSummary run={activeRun} />
          <NotebookDrawer run={activeRun} />
        </> : <div className="panel-empty">Inspecting the wing…</div>}
      </main>
    </div>
  );
}

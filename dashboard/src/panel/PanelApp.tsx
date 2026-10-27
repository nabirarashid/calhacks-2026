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

const PARAM_NAMES: Record<string, string> = {
  aoa_deg: 'Angle of attack', span_mm: 'Span', chord_mm: 'Chord', flap_angle_deg: 'Flap angle',
  flap_chord_frac: 'Flap chord', endplate_height_mm: 'Endplate height',
};

function label(value: string) {
  const name = PARAM_NAMES[value] ?? value.replace(/_(deg|mm|frac|n)$/, '').replaceAll('_', ' ');
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function lower(value: string) {
  return label(value).toLowerCase();
}

/** The investigator replaces numbers it can't trace to simulation data with [?]; show that plainly. */
function withRedactions(text: string) {
  return text.split(/(~?\[\?\]%?)/).map((part, index) => /^~?\[\?\]%?$/.test(part)
    ? <span key={index} className="redacted" title="Removed: not backed by simulation data">unverified</span>
    : part);
}

function principleName(id: string) {
  return id.replace(/^P-/, '').toLowerCase();
}

function metricLabel(value: string) {
  const names: Record<string, string> = {
    downforce_n: 'Downforce', drag_n: 'Drag', l_over_d: 'L/D', drag_induced_n: 'Induced drag',
    drag_profile_n: 'Profile drag', stall_margin_deg: 'Stall margin', span_efficiency: 'Span efficiency',
    cl: 'Lift coefficient',
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

/** Predicted band vs measured value on a symmetric % scale centred on zero. */
function RangeBar({ low, high, actual, tone }: { low: number; high: number; actual?: number; tone: string }) {
  const extent = Math.max(Math.abs(low), Math.abs(high), Math.abs(actual ?? 0), 5) * 1.15;
  const x = (value: number) => 50 + (value / extent) * 50;
  const left = x(Math.min(low, high));
  const width = Math.max(x(Math.max(low, high)) - left, 1.2);
  return (
    <span className="range-bar" aria-hidden="true">
      <i className="range-zero" />
      <i className="range-band" style={{ left: `${left}%`, width: `${width}%` }} />
      {actual === undefined ? null : <i className={`range-dot ${tone}`} style={{ left: `${x(actual)}%` }} />}
    </span>
  );
}

function StepCard({ run, step }: { run: RunFoldState; step: number }) {
  const plan = run.hypotheses.find((item) => item.step === step);
  const result = run.stepResults.find((item) => item.step === step);
  if (!plan) return null;
  const best = result ? run.designsById[result.best_id] : null;
  return (
    <article className={`step-card ${result ? `step-${result.verdict}` : 'step-running'}`}>
      <div className="step-rail"><span>{String(step).padStart(2, '0')}</span><i /></div>
      <div className="step-body">
        <header>
          <div><span className="step-kicker">Hypothesis {step}</span><h2>{plan.levers.map(label).join(' + ')}</h2></div>
          <span className={`verdict verdict-${result?.verdict ?? 'testing'}`}><i />{result?.verdict ?? 'testing'}</span>
        </header>
        <p className="hypothesis">{withRedactions(plan.rationale)}</p>
        <div className="principles">
          {plan.principle_ids.length ? <>Based on <b>{plan.principle_ids.map(principleName).join(', ')}</b></> : 'Exploratory step'}
          {plan.source === 'rules' ? ' · rules fallback' : null}
        </div>
        <div className="prediction-table">
          <div className="prediction-heading"><span>Prediction</span><span><i className="key-band" />predicted <i className="key-dot" />measured</span></div>
          {plan.predictions.map((prediction) => {
            const check = result?.checks.find((item) => item.metric === prediction.metric);
            const tone = check ? check.in_range ? 'accurate' : check.direction_ok ? 'close' : 'miss' : '';
            return (
              <div className="prediction-row" key={prediction.metric}>
                <span className="metric-name">{metricLabel(prediction.metric)}<small>{signed(prediction.pct_low).replace('%', '')} to {signed(prediction.pct_high)}</small></span>
                <RangeBar low={prediction.pct_low} high={prediction.pct_high} actual={check?.actual_pct} tone={tone} />
                <span className={`actual ${tone}`}>{check ? <>{signed(check.actual_pct)}<i className="mark" title={check.in_range ? 'Within the predicted range' : check.direction_ok ? 'Right direction, outside the range' : 'Prediction missed'}>{check.in_range ? '✓' : check.direction_ok ? '~' : '✗'}</i></> : '…'}</span>
              </div>
            );
          })}
        </div>
        {best && result ? <div className="result-strip">Best tested: {plan.levers.map((lever) => `${lower(lever)} ${best.params[lever]} ${run.designSpace?.parameters.find((item) => item.name === lever)?.unit ?? ''}`.trim()).join(', ')} · <b>{best.score.metrics.downforce_n?.toFixed(1)} N</b> downforce · <b>{best.score.metrics.drag_n?.toFixed(1)} N</b> drag</div> : null}
        {result ? <>
          <details className="explanation"><summary>Why this happened</summary><p>{withRedactions(result.explanation)}</p></details>
          <div className="lesson"><span>Learned</span>{withRedactions(result.lesson)}</div>
        </> : <div className="simulating"><i />Testing {plan.candidates.length} design{plan.candidates.length === 1 ? '' : 's'}…</div>}
      </div>
    </article>
  );
}

function NotebookDrawer({ run }: { run: RunFoldState }) {
  const notebook = run.notebook;
  return (
    <details className="notebook-drawer">
      <summary><span><b>Lab notebook</b><small>{notebook.beliefs.length} lessons · {notebook.ruled_out.length} ruled out</small></span><span>Show</span></summary>
      <div className="notebook-content">
        <section><h3>Lessons</h3>{notebook.beliefs.length ? notebook.beliefs.map((belief, index) => <p key={`${index}-${belief.text}`}><b>{belief.evidence_steps.join(', ')}</b><span>{withRedactions(belief.text)}</span></p>) : <em>No observations yet.</em>}</section>
        <section><h3>Measured lever effects</h3>{Object.entries(notebook.lever_effects).map(([lever, effects]) => <div className="lever-effect" key={lever}><b>{label(lever)}</b><span>{Object.entries(effects).map(([metric, value]) => `${metricLabel(metric)} ${value > 0 ? '+' : ''}${value.toFixed(2)}`).join(' · ')}</span></div>)}</section>
        {notebook.ruled_out.length ? <section><h3>Ruled out</h3>{notebook.ruled_out.map((item) => <p key={item}><b>×</b><span>{label(item)}</span></p>)}</section> : null}
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
      <h2>{signed(downforce)} downforce</h2><p>Drag changed {signed(drag)}</p>
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
  const paramNames = inspection?.params.map((param) => param.name) ?? activeRun?.designSpace?.parameters.map((param) => param.name) ?? [];
  const fixed = sessionScope?.fixed ?? paramNames.filter((name) => !editable.includes(name));
  const scoped = editable.length > 0;
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
      <header className="panel-header"><div className="darwin-glyph" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M4 18.5C9 12 19 10.5 28 14.5C20 15.5 11 17.5 4 18.5Z" /><path d="M4 18.5L28 14.5" className="chord" /></svg></div><div><strong>Darwin</strong><span>Aerodynamic design agent</span></div><div className={`panel-status status-${running ? 'live' : 'ready'}`}><i />{running ? sourceStatus : activeRun ? 'complete' : 'ready'}</div></header>
      <main>
        <section className="prompt-card">
          <label htmlFor="design-goal">Design goal</label>
          <textarea id="design-goal" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={4} disabled={running} />
          {scoped ? <>
            <div className="scope-block"><span>Can change</span><div>{editable.map((item) => <b key={item}>{label(item)}</b>)}</div></div>
            {fixed.length ? <div className="scope-block keep"><span>Fixed</span><div>{fixed.map((item) => <b key={item}>{label(item)}</b>)}</div></div> : null}
          </> : inspection ? <div className="param-list">
            <span>Read from Onshape</span>
            {inspection.params.map((param) => <div key={param.name}><span>{label(param.name)}</span><b className="num">{typeof param.value === 'number' ? Number(param.value.toFixed(3)) : String(param.value)} {param.unit === 'frac' ? '' : param.unit}</b></div>)}
          </div> : null}
          {running ? <button className="panel-button stop" type="button" onClick={() => void stop()} disabled={busy}>Stop after this step</button> : <button className="panel-button" type="button" onClick={() => void start()} disabled={busy || !prompt.trim()}>{busy ? 'Starting…' : activeRun ? 'Run again' : 'Start'}</button>}
        </section>

        {error ? <div className="panel-error" role="alert">{error}</div> : null}
        {activeRun ? <>
          <AccuracySparkline values={activeRun.notebook.accuracy} />
          <section className="timeline" aria-label="Investigation steps">
            {steps.map((step) => <StepCard key={step} run={activeRun} step={step} />)}
            {!steps.length ? <div className="panel-empty">Reading the model and simulating the baseline…</div> : null}
          </section>
          <FinalSummary run={activeRun} />
          <NotebookDrawer run={activeRun} />
        </> : <div className="panel-empty">Reading the wing from Onshape…</div>}
      </main>
    </div>
  );
}

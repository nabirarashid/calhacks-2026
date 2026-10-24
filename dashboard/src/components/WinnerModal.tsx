import type { AgentMessage, DesignResult, MetricInfo, RunSummary, Score } from '@shared/contracts';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, api, type ApprovalRecord, type CommitPreview, type CommitResult } from '@/lib/api';
import {
  constraintReview,
  correctionSequence,
  displayCommitValue,
  isExactApproval,
  parameterChanges,
  previewParameterChanges,
  previewTarget,
  reviewCommitResult,
} from './winnerReview';

interface WinnerModalProps {
  summary: RunSummary;
  designs: DesignResult[];
  critic?: AgentMessage;
  docUrl?: string | null;
  onClose: () => void;
  onApprove: (design: DesignResult, approvedBy?: string) => Promise<unknown>;
  onReport: () => void;
  onApprovalStatus?: () => Promise<ApprovalRecord>;
  onCommitPreview?: (design: DesignResult) => Promise<CommitPreview>;
  onCommit?: (design: DesignResult) => Promise<CommitResult>;
  metricCatalog?: MetricInfo[];
}

function HifiCheck({ score }: { score?: Score | null }) {
  if (!score) return <p className="text-xs text-slate-500">High-fidelity check was not available for this run.</p>;
  return (
    <div className="rounded-xl border border-mint/20 bg-mint/[0.04] p-3 text-xs text-slate-300">
      <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-mint">High-fidelity · {score.fidelity}</div>
      {score.warnings.length ? score.warnings.join(' · ') : 'Validation completed without additional warnings.'}
    </div>
  );
}

function expectedCallsLabel(value: CommitPreview['expected_calls']): string {
  if (typeof value === 'number') return `${value} Onshape call${value === 1 ? '' : 's'}`;
  if (Array.isArray(value)) return value.length ? value.join(' · ') : 'No calls expected';
  if (value && typeof value === 'object') {
    const entries = Object.entries(value);
    return entries.length ? entries.map(([name, count]) => `${name}: ${count}`).join(' · ') : 'No calls expected';
  }
  return 'Unavailable';
}

function plannedCheckLabel(check: string | Record<string, unknown>): string {
  if (typeof check === 'string') return check;
  for (const key of ['label', 'name', 'id', 'detail']) {
    if (typeof check[key] === 'string') return check[key] as string;
  }
  return 'Unnamed verification check';
}

function ValueTable({ values, empty }: { values?: Record<string, unknown>; empty: string }) {
  if (!values) return <p className="mt-1 text-[11px] text-rose-300">{empty}</p>;
  const entries = Object.entries(values);
  if (!entries.length) return <p className="mt-1 text-[11px] text-slate-500">No values changed.</p>;
  return <div className="mt-1 max-h-28 overflow-auto"><table className="w-full text-left text-[11px]"><tbody>
    {entries.map(([name, value]) => <tr className="border-t border-line/60" key={name}><td className="py-1 text-slate-400">{name}</td><td className="font-mono text-white">{displayCommitValue(value)}</td></tr>)}
  </tbody></table></div>;
}

export function WinnerModal({
  summary,
  designs,
  critic,
  docUrl,
  onClose,
  onApprove,
  onReport,
  onApprovalStatus,
  onCommitPreview,
  onCommit,
  metricCatalog = [],
}: WinnerModalProps) {
  const champion = summary.champion;
  const seed = summary.seed_design;
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [approvedBy, setApprovedBy] = useState('');
  const [approval, setApproval] = useState<ApprovalRecord | null>(null);
  const [commitPreview, setCommitPreview] = useState<CommitPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirmingCommit, setConfirmingCommit] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const baseline = useMemo(() => {
    const entries = Object.entries(summary.baseline_best);
    return entries.sort(([, a], [, b]) => b.score.aggregate - a.score.aggregate)[0];
  }, [summary.baseline_best]);
  const displayedMetrics = useMemo(() => {
    if (!champion) return [];
    const constraintMetrics = summary.goal.constraints
      .map((constraint) => constraint.ref)
      .filter((name) => !name.startsWith('param:'));
    const ordered = [...summary.goal.objectives.map((objective) => objective.metric), ...constraintMetrics, ...metricCatalog.map((metric) => metric.name)];
    return [...new Set(ordered)].filter((name) => metricCatalog.some((metric) => metric.name === name) && typeof champion.score.metrics[name] === 'number').slice(0, 7);
  }, [champion, metricCatalog, summary.goal.constraints, summary.goal.objectives]);

  const championBinding = champion ? `${champion.design_id}:${champion.param_hash}` : null;
  useEffect(() => {
    setApproval(null);
    setCommitPreview(null);
    setPreviewError(null);
    setCommitResult(null);
    setConfirmingCommit(false);
    if (!champion) return;
    let cancelled = false;
    const loadApproval = onApprovalStatus ?? (() => api.approval(summary.run_id));
    const loadPreview = onCommitPreview ?? (() => api.commitPreview(summary.run_id));
    void loadApproval().then((record) => {
      if (!cancelled && isExactApproval(record, champion)) setApproval(record);
    }).catch((cause) => {
      if (!cancelled && !(cause instanceof ApiError && cause.status === 404)) {
        setFeedback(`Could not verify champion approval: ${cause instanceof Error ? cause.message : String(cause)}`);
      }
    });
    void loadPreview(champion).then((preview) => {
      if (!cancelled) setCommitPreview(preview);
    }).catch((cause) => {
      if (!cancelled) setPreviewError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => { cancelled = true; };
  }, [championBinding, summary.run_id, onApprovalStatus, onCommitPreview]);

  if (!champion) return null;
  const changes = parameterChanges(seed, champion);
  const constraints = constraintReview(summary.goal, champion);
  const sequence = correctionSequence(designs, champion);
  const geometry = champion.geometry;
  const approved = isExactApproval(approval, champion);
  const writeEnabled = approved && commitPreview?.maturity === 4;
  const reviewedCommit = commitResult ? reviewCommitResult(commitResult) : null;

  const approveChampion = async () => {
    setBusy('Approve design');
    setFeedback(null);
    try {
      const raw = await onApprove(champion, approvedBy.trim() || undefined);
      const record = raw as ApprovalRecord;
      if (!isExactApproval(record, champion)) {
        setApproval(null);
        setFeedback('Approval was not bound to this exact champion; version creation remains blocked.');
        return;
      }
      setApproval(record);
      setFeedback('Exact champion approved.');
    } catch (cause) {
      setFeedback(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const refreshPreview = async () => {
    setBusy('Load commit preview');
    setPreviewError(null);
    try {
      const preview = await (onCommitPreview ?? (() => api.commitPreview(summary.run_id)))(champion);
      setCommitPreview(preview);
    } catch (cause) {
      setCommitPreview(null);
      setPreviewError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  const createVersion = async () => {
    if (!writeEnabled || !isExactApproval(approval, champion)) {
      setFeedback('Version creation is blocked until this exact champion is approved and maturity is 4.');
      return;
    }
    setBusy('Create Onshape Version');
    setCommitResult(null);
    setFeedback(null);
    try {
      const result = await (onCommit ?? ((design) => api.commit(summary.run_id, design.design_id)))(champion);
      setCommitResult(result);
      const reviewed = reviewCommitResult(result);
      setFeedback(reviewed.success ? `Created verified Onshape version ${reviewed.versionName}.` : 'Version creation did not complete safely; review the evidence below.');
    } catch (cause) {
      setFeedback(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Winning design">
      <div className="modal-card winner-card">
        <button className="modal-close" type="button" onClick={onClose} aria-label="Close winner card">×</button>
        <div className="eyebrow text-mint">Evolution complete</div>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">The winning design</h2>
            <p className="mt-1 max-w-2xl text-sm text-slate-400">{champion.rationale || summary.goal.source_text}</p>
          </div>
          <div className="text-right">
            <div className="font-mono text-3xl font-semibold text-mint">{champion.score.aggregate.toFixed(3)}</div>
            <div className="font-mono text-[9px] uppercase tracking-widest text-slate-600">aggregate score</div>
          </div>
        </div>

        <div className="mt-6 grid gap-5 lg:grid-cols-[1.25fr_.75fr]">
          <div className="overflow-hidden rounded-xl border border-line">
            <table className="w-full text-left text-xs">
              <thead className="bg-white/[0.025] font-mono text-[9px] uppercase tracking-wider text-slate-500">
                <tr><th className="px-3 py-2">Metric</th><th>Before</th><th>Winner</th><th>Delta</th></tr>
              </thead>
              <tbody>
                {displayedMetrics.flatMap((metric) => {
                  const after = champion.score.metrics[metric];
                  if (typeof after !== 'number') return [];
                  const before = seed?.score.metrics[metric];
                  const info = metricCatalog.find((item) => item.name === metric)!;
                  return [
                    <tr key={metric} className="border-t border-line/80">
                      <td className="px-3 py-2.5 text-slate-400" title={info.description}>{info.name.replace(/_/g, ' ')}</td>
                      <td className="font-mono text-slate-500">{before?.toFixed(2) ?? '—'}{typeof before === 'number' && info.unit ? ` ${info.unit}` : ''}</td>
                      <td className="font-mono font-semibold text-white">{after.toFixed(2)}{info.unit ? ` ${info.unit}` : ''}</td>
                      <td className="font-mono text-mint">{typeof before === 'number' ? `${after - before >= 0 ? '+' : ''}${(after - before).toFixed(2)}${info.unit ? ` ${info.unit}` : ''}` : '—'}</td>
                    </tr>,
                  ];
                })}
                {!displayedMetrics.length ? <tr><td className="px-3 py-3 text-slate-500" colSpan={4}>No catalog-backed metrics were returned.</td></tr> : null}
              </tbody>
            </table>
          </div>
          <div className="space-y-3">
            <div className="rounded-xl border border-line bg-ink/50 p-3">
              <div className="eyebrow">Why it won</div>
              <p className="mt-2 text-xs leading-relaxed text-slate-300">{critic?.body || critic?.summary || champion.rationale || 'The optimizer improved the objective mix while maintaining every hard constraint.'}</p>
            </div>
            <div className="rounded-xl border border-line bg-ink/50 p-3">
              <div className="eyebrow">Matched-budget result</div>
              <p className="mt-2 text-xs text-slate-300">
                {baseline
                  ? `Darwin ${champion.score.aggregate >= baseline[1].score.aggregate ? 'beat' : 'trailed'} ${baseline[0]} by ${Math.abs(champion.score.aggregate - baseline[1].score.aggregate).toFixed(3)} aggregate points.`
                  : 'No baseline result was recorded.'}
              </p>
            </div>
            <HifiCheck score={summary.hifi_check} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
          <label className="flex items-center gap-2 text-xs text-slate-400">Approved by
            <input className="w-36 rounded-md border border-line bg-ink px-2 py-1.5 text-xs text-white" value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} placeholder="Name (optional)" />
          </label>
          <button className="control-button primary" type="button" disabled={busy !== null || approved} onClick={() => void approveChampion()}>{approved ? 'Exact champion approved' : 'Approve design'}</button>
          <button className="control-button primary" type="button" disabled={busy !== null || !writeEnabled} onClick={() => { setCommitResult(null); setConfirmingCommit(true); }}>Create Onshape Version</button>
          <button className="control-button secondary" type="button" onClick={onReport}>Engineering report</button>
          {feedback ? <span className="ml-auto font-mono text-[10px] text-slate-400">{feedback}</span> : null}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
          <span className={approved ? 'text-mint' : 'text-amber'}>{approved ? 'Approval matches champion ID and parameter hash.' : 'Exact champion approval required.'}</span>
          <span className={commitPreview?.maturity === 4 ? 'text-mint' : 'text-amber'}>
            {commitPreview ? `Maturity ${commitPreview.maturity ?? 'missing'}${commitPreview.maturity === 4 ? ' · write-enabled' : ' · write blocked'}` : `Commit preview unavailable${previewError ? `: ${previewError}` : '.'}`}
          </span>
          {(!commitPreview || previewError) ? <button className="rounded border border-line px-2 py-1 text-cyan" type="button" disabled={busy !== null} onClick={() => void refreshPreview()}>Retry preview</button> : null}
        </div>

        <section className="mt-5 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-line bg-ink/50 p-3">
            <div className="eyebrow">Seed → champion parameters</div>
            {changes.length ? <div className="mt-2 max-h-36 overflow-auto">
              <table className="w-full text-left text-[11px]"><thead className="font-mono text-[9px] uppercase text-slate-600"><tr><th>Parameter</th><th>Seed</th><th>Champion</th></tr></thead><tbody>
                {changes.map((change) => <tr className="border-t border-line/60" key={change.name}><td className="py-1.5 text-slate-400">{change.name}</td><td className="font-mono text-slate-500">{change.before}</td><td className="font-mono text-white">{change.after}</td></tr>)}
              </tbody></table>
            </div> : <p className="mt-2 text-xs text-slate-500">No parameter changes from the seed.</p>}
          </div>
          <div className="rounded-xl border border-line bg-ink/50 p-3">
            <div className="eyebrow">CAD regeneration evidence</div>
            <p className={`mt-2 text-xs ${geometry?.status === 'ready' ? 'text-mint' : 'text-amber'}`}>
              {geometry?.status === 'ready'
                ? `Geometry ready · ${geometry.regen_status || 'regeneration status unavailable'} · ${geometry.triangles ?? '—'} triangles · ${geometry.source}`
                : geometry?.status === 'failed'
                  ? `Geometry generation failed${geometry.regen_status ? ` · ${geometry.regen_status}` : ''}${geometry.error ? ` · ${geometry.error}` : ''}`
                  : geometry?.status === 'skipped'
                    ? `Geometry generation skipped${geometry.error ? ` · ${geometry.error}` : ''}`
                    : geometry?.status === 'pending'
                      ? 'Geometry generation is pending.'
                      : 'No CAD regeneration result was recorded for this champion.'}
            </p>
            {geometry?.status === 'ready' && docUrl ? <a className="mt-2 inline-block text-xs text-cyan" href={docUrl} target="_blank" rel="noreferrer">Open Onshape document ↗</a> : null}
          </div>
        </section>

        <section className="mt-4 rounded-xl border border-line bg-ink/50 p-3">
          <div className="eyebrow">Goal constraint review</div>
          {constraints.length ? <div className="mt-2 overflow-x-auto"><table className="w-full text-left text-[11px]"><thead className="font-mono text-[9px] uppercase text-slate-600"><tr><th>Constraint</th><th>Actual</th><th>Limit</th><th>Margin</th><th>Result</th></tr></thead><tbody>
            {constraints.map((item) => <tr className="border-t border-line/60" key={`${item.ref}:${item.op}:${item.limit}`}><td className="py-1.5 text-slate-400">{item.label || item.ref}{item.hard ? ' · hard' : ' · soft'}</td><td className="font-mono">{item.actual?.toFixed(3) ?? 'Unavailable'}</td><td className="font-mono">{item.op} {item.limit}</td><td className="font-mono">{item.margin?.toFixed(3) ?? '—'}</td><td className={item.passed === null ? 'text-amber' : item.passed ? 'text-mint' : 'text-rose-400'}>{item.passed === null ? 'Unknown' : item.passed ? 'Pass' : 'Fail'}</td></tr>)}
          </tbody></table></div> : <p className="mt-2 text-xs text-slate-500">No constraints were specified for this goal.</p>}
        </section>

        <section className="mt-4 rounded-xl border border-line bg-ink/50 p-3">
          <div className="eyebrow">Failure → correction sequence</div>
          <ol className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
            {sequence.map((design, index) => <li className="flex items-center gap-2" key={design.design_id}>
              {index ? <span className="text-slate-600">→</span> : null}
              <span className="rounded-lg border border-line px-2 py-1.5"><span className={design.score.feasible ? 'text-mint' : 'text-rose-400'}>{design.score.feasible ? 'Feasible' : 'Constraint failure'}</span><span className="ml-2 font-mono text-slate-500">g{design.generation} · {design.design_id.split('-').at(-1)}</span></span>
            </li>)}
          </ol>
        </section>

        {confirmingCommit && commitPreview ? (
          <div className="fixed inset-0 z-50 grid place-items-center bg-black/75 p-4" role="alertdialog" aria-modal="true" aria-label="Confirm Onshape version creation">
            <div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-2xl border border-line bg-panel p-5 shadow-2xl">
              <div className="flex items-start justify-between gap-4">
                <div><div className="eyebrow text-amber">Write confirmation</div><h3 className="mt-1 text-xl font-semibold text-white">Create Onshape Version</h3></div>
                <button className="text-xl text-slate-500 hover:text-white" type="button" disabled={busy !== null} onClick={() => setConfirmingCommit(false)} aria-label="Cancel version creation">×</button>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg border border-line p-3"><div className="eyebrow">Target</div><div className="mt-1 text-xs text-white">{previewTarget(commitPreview)}</div></div>
                <div className="rounded-lg border border-line p-3"><div className="eyebrow">Expected calls</div><div className="mt-1 text-xs text-white">{expectedCallsLabel(commitPreview.expected_calls)}</div></div>
                <div className={`rounded-lg border p-3 ${commitPreview.maturity === 4 ? 'border-mint/30' : 'border-rose-400/40'}`}><div className="eyebrow">Maturity</div><div className={commitPreview.maturity === 4 ? 'mt-1 text-xs text-mint' : 'mt-1 text-xs text-rose-300'}>Level {commitPreview.maturity ?? 'missing'} · {commitPreview.maturity === 4 ? 'write-enabled' : 'blocked'}</div></div>
              </div>

              <div className="mt-4 rounded-lg border border-line p-3">
                <div className="eyebrow">Configuration diff</div>
                {previewParameterChanges(commitPreview).length ? <table className="mt-2 w-full text-left text-[11px]"><thead className="font-mono text-[9px] uppercase text-slate-600"><tr><th>Parameter</th><th>Current</th><th>Planned</th></tr></thead><tbody>
                  {previewParameterChanges(commitPreview).map((change) => <tr className="border-t border-line/60" key={change.name}><td className="py-1.5 text-slate-400">{change.name}</td><td className="font-mono text-slate-500">{displayCommitValue(change.before)}</td><td className="font-mono text-white">{displayCommitValue(change.after)}</td></tr>)}
                </tbody></table> : <p className="mt-2 text-xs text-slate-500">No parameter changes returned.</p>}
              </div>

              <div className="mt-3 rounded-lg border border-line p-3">
                <div className="eyebrow">Planned verification</div>
                {Array.isArray(commitPreview.checks_planned) && commitPreview.checks_planned.length ? <ul className="mt-2 space-y-1 text-xs text-slate-300">
                  {commitPreview.checks_planned.map((check, index) => <li key={`${plannedCheckLabel(check)}:${index}`}>• {plannedCheckLabel(check)}</li>)}
                </ul> : <p className="mt-2 text-xs text-rose-300">No verification checks were returned; commit is blocked.</p>}
              </div>

              {reviewedCommit ? (
                <div className={`mt-4 rounded-xl border p-4 ${reviewedCommit.success ? 'border-mint/40 bg-mint/[.04]' : 'border-rose-400/40 bg-rose-400/[.04]'}`} aria-live="polite">
                  <div className={reviewedCommit.success ? 'text-sm font-semibold text-mint' : 'text-sm font-semibold text-rose-300'}>{reviewedCommit.success ? 'Verified version created' : reviewedCommit.partial ? 'Partial write · recovery required' : 'Version not verified'}</div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div><div className="eyebrow">Written values</div><ValueTable values={reviewedCommit.writtenValues} empty="Written values were not returned." /></div>
                    <div><div className="eyebrow">Read-back</div><ValueTable values={reviewedCommit.readBack} empty="Read-back values were not returned." /></div>
                    <div><div className="eyebrow">Geometry check</div><p className={`mt-1 text-[11px] ${reviewedCommit.geometryPassed && reviewedCommit.geometry.status === 'ready' ? 'text-mint' : 'text-rose-300'}`}>{reviewedCommit.geometryPassed && reviewedCommit.geometry.status === 'ready' ? 'Passed' : 'Not passed'} · {reviewedCommit.geometry.status ?? 'status missing'} · {reviewedCommit.geometryDetail}</p></div>
                    <div><div className="eyebrow">Version name</div><p className="mt-1 font-mono text-[11px] text-white">{reviewedCommit.versionName ?? 'Not created / not returned'}</p></div>
                  </div>
                  {reviewedCommit.issues.length ? <ul className="mt-3 space-y-1 text-[11px] text-rose-200">{reviewedCommit.issues.map((issue) => <li key={issue}>• {issue}</li>)}</ul> : null}
                  {reviewedCommit.partial ? <div className="mt-3 rounded-lg border border-amber/30 bg-amber/[.04] p-3"><div className="eyebrow text-amber">Recovery steps</div><ol className="mt-2 space-y-1 text-[11px] text-slate-300">{reviewedCommit.recoverySteps.map((step, index) => <li key={step}>{index + 1}. {step}</li>)}</ol></div> : null}
                </div>
              ) : null}

              <div className="mt-5 flex justify-end gap-2">
                <button className="control-button secondary" type="button" disabled={busy !== null} onClick={() => setConfirmingCommit(false)}>{reviewedCommit ? 'Close' : 'Cancel'}</button>
                {!reviewedCommit ? <button className="control-button primary" type="button" disabled={busy !== null || !writeEnabled || !Array.isArray(commitPreview.checks_planned) || commitPreview.checks_planned.length === 0} onClick={() => void createVersion()}>{busy === 'Create Onshape Version' ? 'Writing…' : 'Confirm write, verify & version'}</button> : null}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

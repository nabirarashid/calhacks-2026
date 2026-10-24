import type { AgentMessage, DesignResult, RunSummary, Score } from '@shared/contracts';
import { useMemo, useState } from 'react';
import { constraintReview, correctionSequence, parameterChanges } from './winnerReview';

interface WinnerModalProps {
  summary: RunSummary;
  designs: DesignResult[];
  critic?: AgentMessage;
  docUrl?: string | null;
  onClose: () => void;
  onApprove: (design: DesignResult, approvedBy?: string) => Promise<unknown>;
  onReport: () => void;
}

const METRICS = ['stability_margin_cal', 'drag_n', 'fin_mass_total_g', 'flutter_margin', 'aft_overhang_mm'];

function HifiCheck({ score }: { score?: Score | null }) {
  if (!score) return <p className="text-xs text-slate-500">High-fidelity check was not available for this run.</p>;
  return (
    <div className="rounded-xl border border-mint/20 bg-mint/[0.04] p-3 text-xs text-slate-300">
      <div className="mb-1 font-mono text-[9px] uppercase tracking-wider text-mint">High-fidelity · {score.fidelity}</div>
      {score.warnings.length ? score.warnings.join(' · ') : 'Validation completed without additional warnings.'}
    </div>
  );
}

export function WinnerModal({ summary, designs, critic, docUrl, onClose, onApprove, onReport }: WinnerModalProps) {
  const champion = summary.champion;
  const seed = summary.seed_design;
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [approvedBy, setApprovedBy] = useState('');
  const baseline = useMemo(() => {
    const entries = Object.entries(summary.baseline_best);
    return entries.sort(([, a], [, b]) => b.score.aggregate - a.score.aggregate)[0];
  }, [summary.baseline_best]);

  if (!champion) return null;
  const changes = parameterChanges(seed, champion);
  const constraints = constraintReview(summary.goal, champion);
  const sequence = correctionSequence(designs, champion);
  const geometry = champion.geometry;
  const runAction = async (name: string, action: () => Promise<unknown>) => {
    setBusy(name);
    setFeedback(null);
    try {
      await action();
      setFeedback(`${name} complete`);
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
            <h2 className="text-3xl font-semibold tracking-tight text-white">The winning fin</h2>
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
                {METRICS.flatMap((metric) => {
                  const after = champion.score.metrics[metric];
                  if (typeof after !== 'number') return [];
                  const before = seed?.score.metrics[metric];
                  return [
                    <tr key={metric} className="border-t border-line/80">
                      <td className="px-3 py-2.5 text-slate-400">{metric.replace(/_/g, ' ')}</td>
                      <td className="font-mono text-slate-500">{before?.toFixed(2) ?? '—'}</td>
                      <td className="font-mono font-semibold text-white">{after.toFixed(2)}</td>
                      <td className="font-mono text-mint">{typeof before === 'number' ? `${after - before >= 0 ? '+' : ''}${(after - before).toFixed(2)}` : '—'}</td>
                    </tr>,
                  ];
                })}
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
          <button className="control-button primary" type="button" disabled={busy !== null} onClick={() => void runAction('Approve design', () => onApprove(champion, approvedBy.trim() || undefined))}>Approve design</button>
          <button className="control-button secondary" type="button" onClick={onReport}>Engineering report</button>
          {feedback ? <span className="ml-auto font-mono text-[10px] text-slate-400">{feedback}</span> : null}
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
      </div>
    </div>
  );
}

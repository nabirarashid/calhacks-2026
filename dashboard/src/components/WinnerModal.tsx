import type { AgentMessage, DesignResult, GeometryRef, RunSummary, Score } from '@shared/contracts';
import { useMemo, useState } from 'react';

interface WinnerModalProps {
  summary: RunSummary;
  critic?: AgentMessage;
  docUrl?: string | null;
  onClose: () => void;
  onCommit: (design: DesignResult) => Promise<GeometryRef>;
  onExport: (design: DesignResult) => Promise<void>;
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

export function WinnerModal({ summary, critic, docUrl, onClose, onCommit, onExport, onReport }: WinnerModalProps) {
  const champion = summary.champion;
  const seed = summary.seed_design;
  const [busy, setBusy] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const baseline = useMemo(() => {
    const entries = Object.entries(summary.baseline_best);
    return entries.sort(([, a], [, b]) => b.score.aggregate - a.score.aggregate)[0];
  }, [summary.baseline_best]);

  if (!champion) return null;
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
          {docUrl ? <a className="control-button secondary" href={docUrl} target="_blank" rel="noreferrer">Open in Onshape ↗</a> : null}
          <button className="control-button secondary" disabled={busy !== null} onClick={() => void runAction('Commit', () => onCommit(champion))}>Commit to Onshape</button>
          <button className="control-button secondary" disabled={busy !== null} onClick={() => void runAction('Export', () => onExport(champion))}>Export print</button>
          <button className="control-button primary" type="button" onClick={onReport}>Engineering report</button>
          {feedback ? <span className="ml-auto font-mono text-[10px] text-slate-400">{feedback}</span> : null}
        </div>
      </div>
    </div>
  );
}

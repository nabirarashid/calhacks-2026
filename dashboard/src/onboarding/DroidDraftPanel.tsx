import { useState } from 'react';
import type { CapabilityReportData } from './types';

export interface DroidDraftResult {
  plan: string[];
  steps: Array<{ label: string; status: 'pending' | 'running' | 'passed' | 'failed'; detail?: string }>;
  diff?: string;
  tests: Array<{ name: string; passed: boolean; detail?: string }>;
}

export function DroidDraftPanel({
  report,
  onDraft,
  onOpenManual,
}: {
  report: CapabilityReportData;
  onDraft?: (report: CapabilityReportData) => Promise<DroidDraftResult>;
  onOpenManual?: (result: DroidDraftResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DroidDraftResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const unsupportedText = report.unsupported.join(' ');
  const cfdExcluded = /^cfd(?:_|\*)/i.test(report.required_adapter ?? '') || /\bcfd\b/i.test(unsupportedText);

  const draft = async () => {
    if (!onDraft || cfdExcluded) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await onDraft(report));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-4 rounded-xl border border-cyan/20 bg-cyan/[.025] p-4" aria-label="Draft adapter with Droid">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="eyebrow text-cyan">Factory Droid · sandboxed draft</div>
          <h3 className="mt-1 text-sm font-semibold text-slate-100">Draft a missing solver adapter</h3>
          <p className="mt-1 max-w-2xl text-[10px] leading-relaxed text-slate-500">Droid may draft code and golden tests in an isolated worktree. Draft directories are never loaded by the adapter registry; promotion requires human review.</p>
        </div>
        <button className="control-button secondary" type="button" disabled={!onDraft || busy || cfdExcluded} onClick={() => void draft()}>{busy ? 'Drafting…' : 'Draft adapter with Droid'}</button>
      </div>

      {cfdExcluded ? <p className="mt-3 rounded-lg border border-amber/25 bg-amber/5 p-3 text-xs text-amber">CFD adapters are excluded by project scope, including as generated drafts.</p> : null}
      {!onDraft && !cfdExcluded ? <p className="mt-3 text-[10px] text-slate-500">The local Droid worker is not connected. This project remains at its current maturity.</p> : null}
      {error ? <p className="mt-3 rounded-lg border border-coral/25 bg-coral/5 p-3 text-xs text-coral">{error}</p> : null}

      {result ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-line bg-ink/60 p-3"><div className="eyebrow">Plan</div><ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-slate-400">{result.plan.map((item) => <li key={item}>{item}</li>)}</ol></div>
          <div className="rounded-lg border border-line bg-ink/60 p-3"><div className="eyebrow">Steps</div><ul className="mt-2 space-y-1 text-xs">{result.steps.map((step) => <li className="flex items-start justify-between gap-3" key={step.label}><span className="text-slate-400">{step.label}</span><span className={step.status === 'passed' ? 'text-mint' : step.status === 'failed' ? 'text-coral' : 'text-amber'}>{step.status}</span></li>)}</ul></div>
          <div className="rounded-lg border border-line bg-ink/60 p-3"><div className="eyebrow">Diff</div><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[9px] leading-relaxed text-slate-400">{result.diff || 'No diff returned.'}</pre></div>
          <div className="rounded-lg border border-line bg-ink/60 p-3"><div className="eyebrow">Conformance tests</div><ul className="mt-2 space-y-1 text-xs">{result.tests.map((test) => <li className={test.passed ? 'text-mint' : 'text-coral'} key={test.name}>{test.passed ? '✓' : '×'} {test.name}{test.detail ? ` · ${test.detail}` : ''}</li>)}</ul></div>
          <div className="flex justify-end lg:col-span-2"><button className="control-button secondary" type="button" disabled={!onOpenManual} onClick={() => onOpenManual?.(result)}>Open PR (manual)</button></div>
        </div>
      ) : null}
    </section>
  );
}


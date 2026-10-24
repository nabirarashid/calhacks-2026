import { useId } from 'react';

import type { CapabilityReportData, CadInventory, Maturity } from './types';
import { DroidDraftPanel, type DroidDraftResult } from './DroidDraftPanel';

const maturityNames: Record<Maturity, string> = {
  0: 'Unsupported',
  1: 'Inventory-only',
  2: 'Manifest-reviewed',
  3: 'Solver-ready',
  4: 'Write-enabled',
};

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(displayValue).join(', ');
  if (value && typeof value === 'object') return JSON.stringify(value);
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

export interface CapabilityReportProps {
  report: CapabilityReportData;
  inventory?: CadInventory;
  className?: string;
  onDraftAdapter?: (report: CapabilityReportData) => Promise<DroidDraftResult>;
  onOpenDraftPr?: (result: DroidDraftResult) => void;
}

/**
 * An intentionally non-error presentation of a useful, read-only inspection.
 * The report states the achieved authority and the concrete work needed next.
 */
export function CapabilityReport({ report, inventory, className = '', onDraftAdapter, onOpenDraftPr }: CapabilityReportProps) {
  const titleId = useId();

  return (
    <section
      className={`overflow-hidden rounded-2xl border border-line bg-panel/95 shadow-glow ${className}`}
      aria-labelledby={titleId}
    >
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <div className="eyebrow text-mint">Inspection complete</div>
          <h2 id={titleId} className="mt-1 text-lg font-semibold text-slate-100">
            Capability report
          </h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400">
            Darwin preserved the useful inventory and stopped before making an unsupported engineering claim.
          </p>
        </div>
        <div className="rounded-xl border border-cyan/30 bg-cyan/5 px-3 py-2 text-right">
          <div className="font-mono text-[9px] uppercase tracking-wider text-cyan/70">Maturity {report.maturity}</div>
          <div className="text-sm font-semibold text-cyan">{maturityNames[report.maturity]}</div>
        </div>
      </header>

      <div className="grid gap-4 p-5 lg:grid-cols-3">
        <div className="rounded-xl border border-mint/20 bg-mint/[.035] p-4">
          <h3 className="text-sm font-semibold text-mint">What Darwin found</h3>
          <dl className="mt-3 space-y-2 text-xs">
            {Object.entries(report.found).map(([label, value]) => (
              <div className="flex items-start justify-between gap-3" key={label}>
                <dt className="text-slate-500">{label.replaceAll('_', ' ')}</dt>
                <dd className="max-w-[60%] text-right font-mono text-slate-200">{displayValue(value)}</dd>
              </div>
            ))}
            {inventory ? (
              <>
                <div className="flex items-start justify-between gap-3">
                  <dt className="text-slate-500">configuration inputs</dt>
                  <dd className="font-mono text-slate-200">{inventory.config_inputs.length}</dd>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <dt className="text-slate-500">parts</dt>
                  <dd className="font-mono text-slate-200">{inventory.parts.length}</dd>
                </div>
              </>
            ) : null}
          </dl>
        </div>

        <div className="rounded-xl border border-amber/25 bg-amber/[.035] p-4">
          <h3 className="text-sm font-semibold text-amber">What would unlock the next level</h3>
          {report.missing.length ? (
            <ul className="mt-3 space-y-3">
              {report.missing.map((question) => (
                <li key={question.id} className="text-xs leading-relaxed text-slate-300">
                  <div>{question.prompt}</div>
                  <div className="mt-0.5 font-mono text-[9px] text-slate-500">
                    {question.field} · required for level {question.required_for}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-slate-400">No unanswered manifest fields.</p>
          )}
        </div>

        <div className="rounded-xl border border-slate-700 bg-white/[.018] p-4">
          <h3 className="text-sm font-semibold text-slate-200">Domain support needed</h3>
          {report.unsupported.length ? (
            <ul className="mt-3 space-y-2 text-xs leading-relaxed text-slate-400">
              {report.unsupported.map((item) => <li key={item}>• {item}</li>)}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-slate-400">The installed domain pack covers this object.</p>
          )}
          {report.required_adapter ? (
            <div className="mt-4 rounded-lg border border-line bg-ink/60 p-3">
              <div className="font-mono text-[9px] uppercase tracking-wider text-slate-500">Required adapter</div>
              <div className="mt-1 font-mono text-xs text-cyan">{report.required_adapter}</div>
            </div>
          ) : null}
          <p className="mt-4 text-[10px] leading-relaxed text-slate-500">
            Inventory remains available for review and export planning. Simulation stays disabled until a validated adapter is installed.
          </p>
        </div>
      </div>
      {report.required_adapter ? <div className="border-t border-line px-5 pb-5"><DroidDraftPanel report={report} onDraft={onDraftAdapter} onOpenManual={onOpenDraftPr} /></div> : null}
    </section>
  );
}


import type { DesignResult, Goal, MetricInfo } from '@shared/contracts';
import { constraintReview, correctionSequence } from './winnerReview';
import type { AnalysisProgressSnapshot } from '@/lib/projects';

interface CheckResult {
  id: string;
  passed: boolean | null;
  actual?: number | null;
  limit?: number | null;
  detail?: string;
}

interface AnalysisArtifactView {
  adapter_id: string;
  adapter_version?: string;
  fidelity: 'screening' | 'verification';
  metrics: Record<string, number>;
  converged?: boolean | null;
  mesh?: Record<string, number>;
  validity?: string[];
  diagnostics?: Record<string, number>;
  solver_version?: string;
  elapsed_ms?: number;
  geometry_evidence?: { checks?: CheckResult[] } | null;
}

type DesignWithEvidence = DesignResult & {
  analysis?: AnalysisArtifactView | null;
  geometry?: (DesignResult['geometry'] & { evidence?: { checks?: CheckResult[] } | null }) | null;
};

const format = (value: number | null | undefined, unit = '') => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
};

function outcomeClass(passed: boolean | null) {
  if (passed === true) return 'text-mint';
  if (passed === false) return 'text-coral';
  return 'text-amber';
}

export function StructuralEvidence({
  champion,
  designs,
  goal,
  catalog,
  progress = [],
}: {
  champion?: DesignResult | null;
  designs?: DesignResult[];
  goal?: Goal | null;
  catalog?: MetricInfo[];
  progress?: AnalysisProgressSnapshot[];
}) {
  if (!champion) {
    return (
      <section className="rounded-2xl border border-line bg-panel p-4">
        <div className="eyebrow">Engineering evidence</div>
        <p className="mt-3 text-xs text-slate-500">Evidence appears when a solver-ready project produces an evaluated design.</p>
      </section>
    );
  }

  const evidenceDesign = champion as DesignWithEvidence;
  const analysis = evidenceDesign.analysis;
  const fidelity = analysis?.fidelity ?? (champion.score.fidelity === 'high' ? 'verification' : 'screening');
  const metrics = analysis?.metrics ?? champion.score.metrics;
  const requirements = goal ? constraintReview(goal, { ...champion, score: { ...champion.score, metrics } }) : [];
  const checks = analysis?.geometry_evidence?.checks ?? evidenceDesign.geometry?.evidence?.checks ?? [];
  const sequence = correctionSequence(designs ?? [champion], champion);
  const activeProgress = progress.filter((item) => item.design_id === champion.design_id).at(-1);

  return (
    <section className="rounded-2xl border border-line bg-panel p-4" aria-label="Structural evidence">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="eyebrow">Engineering evidence</div>
          <h3 className="mt-1 text-sm font-semibold text-white">{analysis?.adapter_id ?? 'Recorded solver result'}</h3>
        </div>
        <span className={`rounded-full border px-2 py-1 font-mono text-[9px] uppercase ${fidelity === 'verification' ? 'border-mint/30 bg-mint/5 text-mint' : 'border-amber/30 bg-amber/5 text-amber'}`}>
          {fidelity === 'verification' ? 'FEA verified' : 'screening'}
        </span>
      </div>

      {activeProgress ? (
        <div className="mt-4 rounded-xl border border-cyan/20 bg-cyan/5 p-3">
          <div className="flex items-center justify-between font-mono text-[9px] uppercase tracking-wider text-cyan">
            <span>{activeProgress.adapter_id} · {activeProgress.stage}</span><span>{Math.round(activeProgress.pct)}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/5"><i className="block h-full rounded-full bg-cyan" style={{ width: `${Math.max(0, Math.min(100, activeProgress.pct))}%` }} /></div>
          <div className="mt-1 text-right font-mono text-[9px] text-slate-600">{Math.round(activeProgress.elapsed_ms)} ms</div>
        </div>
      ) : null}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="font-mono text-[9px] uppercase tracking-wider text-slate-600"><tr><th className="pb-2 pr-3">Requirement</th><th className="pb-2 pr-3">Actual</th><th className="pb-2 pr-3">Limit</th><th className="pb-2 pr-3">Fidelity</th><th className="pb-2">Result</th></tr></thead>
          <tbody className="divide-y divide-line/70">
            {requirements.length ? requirements.map((row) => {
              const metricName = row.ref.startsWith('param:') ? '' : row.ref;
              const info = catalog?.find((metric) => metric.name === metricName);
              return (
                <tr key={`${row.ref}:${row.op}:${row.limit}`}>
                  <td className="py-2 pr-3 text-slate-300">{row.label || info?.description || row.ref}</td>
                  <td className="py-2 pr-3 font-mono text-slate-300">{format(row.actual, info?.unit)}</td>
                  <td className="py-2 pr-3 font-mono text-slate-500">{row.op} {format(row.limit, info?.unit)}</td>
                  <td className="py-2 pr-3 text-slate-500">{fidelity}</td>
                  <td className={`py-2 font-semibold ${outcomeClass(row.passed)}`}>{row.passed === true ? 'Pass' : row.passed === false ? 'Fail' : 'Blocked'}</td>
                </tr>
              );
            }) : <tr><td colSpan={5} className="py-3 text-slate-500">No typed requirements were included with this run.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-line bg-white/[.018] p-3">
          <div className="eyebrow">Convergence</div>
          <div className={`mt-2 text-sm font-semibold ${outcomeClass(analysis?.converged ?? null)}`}>{analysis?.converged === true ? 'Two-level check passed' : analysis?.converged === false ? 'Not converged — cannot champion' : 'Not recorded'}</div>
          {analysis?.mesh ? <div className="mt-2 flex flex-wrap gap-2">{Object.entries(analysis.mesh).map(([key, value]) => <span key={key} className="rounded-md border border-line px-2 py-1 font-mono text-[9px] text-slate-500">{key} {format(value)}</span>)}</div> : null}
        </div>
        <div className="rounded-xl border border-line bg-white/[.018] p-3">
          <div className="eyebrow">Protected interfaces</div>
          {checks.length ? <ul className="mt-2 space-y-1.5">{checks.map((check) => <li key={check.id} className="flex items-start justify-between gap-3 text-xs"><span className="text-slate-400">{check.id.replace(/_/g, ' ')}</span><span className={`font-semibold ${outcomeClass(check.passed)}`}>{check.passed === true ? 'Unchanged' : check.passed === false ? 'Changed' : 'Blocked'}</span></li>)}</ul> : <p className="mt-2 text-xs text-slate-500">No protected-interface checks were recorded.</p>}
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-line bg-white/[.018] p-3">
        <div className="eyebrow">Failure → repair</div>
        {sequence.length > 1 ? (
          <ol className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {sequence.map((design, index) => {
              const violation = design.score.violations.find((item) => item.hard);
              return <li key={design.design_id} className={`rounded-lg border p-2 ${design.score.feasible ? 'border-mint/20 bg-mint/5' : 'border-coral/20 bg-coral/5'}`}><div className="font-mono text-[9px] text-slate-500">{index + 1}. {design.design_id.split('-').at(-1)}</div><strong className={design.score.feasible ? 'text-mint' : 'text-coral'}>{design.score.feasible ? 'Requirements pass' : 'Requirement failed'}</strong><p className="mt-1 text-[10px] text-slate-500">{violation ? `${violation.ref}: ${format(violation.actual)} vs ${violation.op} ${format(violation.limit)}` : design.rationale || design.operator}</p></li>;
            })}
          </ol>
        ) : <p className="mt-2 text-xs text-slate-500">No evaluated failure-to-repair ancestry was recorded.</p>}
      </div>

      {analysis?.validity?.length ? <div className="mt-4"><div className="eyebrow">Validity envelope</div><ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-500">{analysis.validity.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
    </section>
  );
}


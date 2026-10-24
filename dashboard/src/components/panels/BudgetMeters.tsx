import type { BudgetStatus } from '@shared/contracts';
import { clamp, EmptyPanel, PANEL_COLORS, PanelFrame, formatCompact } from './panelPrimitives';

export interface BudgetMetersProps {
  budget?: BudgetStatus | null;
  compact?: boolean;
  className?: string;
}

interface MeterProps {
  label: string;
  valueLabel: string;
  value: number;
  max: number;
  color: string;
  warning?: boolean;
  marker?: number;
  markerLabel?: string;
}

function Meter({ label, valueLabel, value, max, color, warning, marker, markerLabel }: MeterProps) {
  const safeMax = Number.isFinite(max) && max > 0 ? max : 1;
  const ratio = clamp((Number.isFinite(value) ? value : 0) / safeMax);
  const markerRatio = marker === undefined ? null : clamp(marker / safeMax);
  return (
    <div className="min-w-32 flex-1">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="font-mono text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
        <span className={`font-mono text-[10px] font-semibold ${warning ? 'text-coral' : 'text-slate-200'}`}>{valueLabel}</span>
      </div>
      <div className="relative h-1.5 overflow-visible rounded-full bg-line" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={safeMax} aria-valuenow={value}>
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${ratio * 100}%`, background: warning ? PANEL_COLORS.danger : color }}
        />
        {markerRatio !== null ? (
          <span
            className="absolute -top-1 h-3.5 w-px bg-coral"
            style={{ left: `${markerRatio * 100}%` }}
            title={markerLabel}
            aria-label={markerLabel}
          />
        ) : null}
      </div>
    </div>
  );
}

export function BudgetMeters({ budget, compact = false, className }: BudgetMetersProps) {
  const content = !budget ? (
    <EmptyPanel label="Budget telemetry pending" detail="Usage limits appear when the run starts." />
  ) : (() => {
    const onshape = budget.onshape;
    const model = budget.model;
    const onshapeScale = Math.max(onshape.remaining_estimate + onshape.calls_session, onshape.reserve * 1.2, 1);
    const meters = (
      <>
        <Meter
          label={`Onshape · ${onshape.account_label || 'account'}`}
          valueLabel={`${formatCompact(onshape.remaining_estimate, 0)} left`}
          value={onshape.remaining_estimate}
          max={onshapeScale}
          color={PANEL_COLORS.cmaes}
          warning={onshape.hard_stop || onshape.remaining_estimate <= onshape.reserve}
          marker={onshape.reserve}
          markerLabel={`Reserve: ${formatCompact(onshape.reserve, 0)} calls`}
        />
        <Meter
          label={`Model run · ${model.provider || 'provider'}`}
          valueLabel={`$${formatCompact(model.spend_run_usd, 3)} / $${formatCompact(model.spend_cap_run_usd, 2)}`}
          value={model.spend_run_usd}
          max={model.spend_cap_run_usd}
          color={PANEL_COLORS.agent}
          warning={model.spend_cap_run_usd > 0 && model.spend_run_usd >= model.spend_cap_run_usd * 0.9}
        />
        {!compact ? (
          <Meter
            label="Model total"
            valueLabel={`$${formatCompact(model.spend_total_usd, 2)} / $${formatCompact(model.spend_cap_total_usd, 2)}`}
            value={model.spend_total_usd}
            max={model.spend_cap_total_usd}
            color="#a78bfa"
            warning={model.spend_cap_total_usd > 0 && model.spend_total_usd >= model.spend_cap_total_usd * 0.9}
          />
        ) : null}
        <Meter
          label="Evaluations"
          valueLabel={`${formatCompact(budget.evals_used, 0)} / ${formatCompact(budget.evals_budget, 0)}`}
          value={budget.evals_used}
          max={budget.evals_budget}
          color={PANEL_COLORS.random}
          warning={budget.evals_budget > 0 && budget.evals_used >= budget.evals_budget}
        />
      </>
    );
    return compact ? (
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-5 gap-y-2">{meters}</div>
    ) : (
      <div className="grid gap-4 p-4 sm:grid-cols-2 xl:grid-cols-4">{meters}</div>
    );
  })();

  if (compact) {
    return (
      <div className={`flex min-w-0 items-center ${className ?? ''}`}>
        {budget ? content : <span className="font-mono text-[10px] uppercase text-slate-500">Budget telemetry pending</span>}
      </div>
    );
  }

  return <PanelFrame title="Resource budget" eyebrow="Hard limits" className={className}>{content}</PanelFrame>;
}

import type { DesignResult, MetricInfo } from '@shared/contracts';

interface MetricChipsProps {
  design: DesignResult | null;
  catalog: MetricInfo[];
}

const PREFERRED = ['stability_margin_cal', 'drag_n', 'fin_mass_total_g', 'flutter_margin'];

const formatMetric = (value: number, unit = '') => {
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
};

export function MetricChips({ design, catalog }: MetricChipsProps) {
  if (!design) return null;
  return (
    <div className="pointer-events-none absolute inset-x-4 bottom-12 z-10 flex flex-wrap gap-2">
      {PREFERRED.flatMap((name) => {
        const value = design.score.metrics[name];
        if (typeof value !== 'number') return [];
        const info = catalog.find((metric) => metric.name === name);
        return [
          <div key={name} className="metric-chip">
            <span>{name.replace(/_/g, ' ')}</span>
            <strong>{formatMetric(value, info?.unit)}</strong>
          </div>,
        ];
      })}
      <div className={`metric-chip ${design.score.feasible ? 'feasible' : 'infeasible'}`}>
        <span>aggregate</span>
        <strong>{design.score.aggregate.toFixed(3)}</strong>
      </div>
    </div>
  );
}

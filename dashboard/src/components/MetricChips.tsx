import type { DesignResult, MetricInfo } from '@shared/contracts';

interface MetricChipsProps {
  design: DesignResult | null;
  catalog: MetricInfo[];
  preferredNames?: string[];
}

const formatMetric = (value: number, unit = '') => {
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)}${unit ? ` ${unit}` : ''}`;
};

export function MetricChips({ design, catalog, preferredNames = [] }: MetricChipsProps) {
  if (!design) return null;
  const catalogByName = new Map(catalog.map((metric) => [metric.name, metric]));
  const names = [...new Set([...preferredNames, ...catalog.map((metric) => metric.name)])]
    .filter((name) => catalogByName.has(name) && typeof design.score.metrics[name] === 'number')
    .slice(0, 4);
  return (
    <div className="pointer-events-none absolute inset-x-4 bottom-12 z-10 flex flex-wrap gap-2">
      {names.flatMap((name) => {
        const value = design.score.metrics[name];
        if (typeof value !== 'number') return [];
        const info = catalogByName.get(name)!;
        return [
          <div key={name} className="metric-chip">
            <span title={info.description}>{info.name.replace(/_/g, ' ')}</span>
            <strong>{formatMetric(value, info.unit)}</strong>
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

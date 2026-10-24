import { useEffect, useMemo, useState } from 'react';
import {
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DesignResult, MetricInfo } from '@shared/contracts';
import { EmptyPanel, ORIGIN_COLORS, PANEL_COLORS, PanelFrame, formatCompact, safeNumber, shortDesignId } from './panelPrimitives';

export interface LandscapeData {
  metrics: [string, string];
  points: Array<[number, number, number, boolean]>;
}

export interface ParetoChartProps {
  designs?: DesignResult[];
  paretoIds?: string[];
  landscape?: LandscapeData | null;
  metricCatalog?: MetricInfo[];
  objectiveMetrics?: string[];
  metrics?: [string, string];
  onMetricsChange?: (metrics: [string, string]) => void;
  selectedDesignId?: string | null;
  onSelectDesign?: (design: DesignResult) => void;
  height?: number;
  className?: string;
}

interface PlotPoint {
  x: number;
  y: number;
  aggregate: number;
  feasible: boolean;
  design?: DesignResult;
}

const generationColor = (generation: number): string => {
  const hue = (154 + Math.max(0, generation) * 23) % 360;
  return `hsl(${hue} 72% 63%)`;
};

export function ParetoChart({
  designs = [],
  paretoIds = [],
  landscape,
  metricCatalog = [],
  objectiveMetrics = [],
  metrics,
  onMetricsChange,
  selectedDesignId,
  onSelectDesign,
  height = 270,
  className,
}: ParetoChartProps) {
  const availableMetrics = useMemo(() => {
    const named = metricCatalog.map((metric) => metric.name);
    const observed = designs.flatMap((design) => Object.keys(design.score?.metrics ?? {}));
    return [...new Set([...objectiveMetrics, ...named, ...observed])];
  }, [designs, metricCatalog, objectiveMetrics]);

  const defaultMetrics: [string, string] = [
    objectiveMetrics[0] ?? availableMetrics[0] ?? '',
    objectiveMetrics[1] ?? availableMetrics[1] ?? availableMetrics[0] ?? '',
  ];
  const [internalMetrics, setInternalMetrics] = useState<[string, string]>(defaultMetrics);
  const activeMetrics = metrics ?? internalMetrics;

  useEffect(() => {
    if (metrics) return;
    setInternalMetrics(([x, y]) => [
      availableMetrics.includes(x) ? x : defaultMetrics[0],
      availableMetrics.includes(y) ? y : defaultMetrics[1],
    ]);
  }, [availableMetrics.join('|'), defaultMetrics[0], defaultMetrics[1], metrics]);

  const setMetric = (axis: 0 | 1, value: string) => {
    const next: [string, string] = [...activeMetrics] as [string, string];
    next[axis] = value;
    if (!metrics) setInternalMetrics(next);
    onMetricsChange?.(next);
  };

  const designPoints = useMemo<PlotPoint[]>(
    () =>
      designs.flatMap((design) => {
        const x = design.score?.metrics?.[activeMetrics[0]];
        const y = design.score?.metrics?.[activeMetrics[1]];
        return typeof x === 'number' && Number.isFinite(x) && typeof y === 'number' && Number.isFinite(y)
          ? [{ x, y, aggregate: safeNumber(design.score.aggregate), feasible: Boolean(design.score.feasible), design }]
          : [];
      }),
    [activeMetrics, designs],
  );

  const landscapePoints = useMemo<PlotPoint[]>(() => {
    if (!landscape || landscape.metrics[0] !== activeMetrics[0] || landscape.metrics[1] !== activeMetrics[1]) return [];
    return landscape.points.flatMap(([x, y, aggregate, feasible]) =>
      Number.isFinite(x) && Number.isFinite(y) ? [{ x, y, aggregate, feasible }] : [],
    );
  }, [activeMetrics, landscape]);

  const paretoPoints = useMemo(() => {
    const ids = new Set(paretoIds);
    return designPoints
      .filter((point) => point.design && ids.has(point.design.design_id))
      .sort((a, b) => a.x - b.x);
  }, [designPoints, paretoIds]);

  const metricUnit = (name: string) => metricCatalog.find((metric) => metric.name === name)?.unit ?? '';
  const hasData = designPoints.length > 0 || landscapePoints.length > 0;

  const selectors = (
    <div className="flex items-center gap-1.5">
      {([0, 1] as const).map((axis) => (
        <select
          key={axis}
          aria-label={`${axis === 0 ? 'X' : 'Y'} axis metric`}
          value={activeMetrics[axis]}
          onChange={(event) => setMetric(axis, event.target.value)}
          className="max-w-36 rounded-md border border-line bg-ink px-2 py-1 font-mono text-[10px] text-slate-300 outline-none focus:border-mint/60"
        >
          {availableMetrics.map((name) => (
            <option value={name} key={name}>{name}</option>
          ))}
        </select>
      ))}
    </div>
  );

  return (
    <PanelFrame title="Pareto landscape" eyebrow={`${paretoIds.length} on front`} action={selectors} className={className}>
      {!hasData ? (
        <EmptyPanel label="Waiting for landscape" detail="Evaluated designs and the simulation cloud will appear here." />
      ) : (
        <div className="px-2 pb-2 pt-3" style={{ height: Math.max(210, height) }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart margin={{ top: 6, right: 12, bottom: 12, left: -8 }}>
              <CartesianGrid stroke={PANEL_COLORS.grid} strokeDasharray="2 5" />
              <XAxis
                type="number"
                dataKey="x"
                name={activeMetrics[0]}
                unit={metricUnit(activeMetrics[0])}
                domain={['auto', 'auto']}
                tick={{ fill: PANEL_COLORS.muted, fontSize: 9 }}
                tickLine={false}
                axisLine={{ stroke: PANEL_COLORS.grid }}
                tickFormatter={(value: number) => formatCompact(value)}
                label={{ value: activeMetrics[0], fill: PANEL_COLORS.muted, fontSize: 9, position: 'insideBottomRight', offset: -8 }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name={activeMetrics[1]}
                unit={metricUnit(activeMetrics[1])}
                domain={['auto', 'auto']}
                tick={{ fill: PANEL_COLORS.muted, fontSize: 9 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(value: number) => formatCompact(value)}
              />
              <Tooltip
                cursor={{ stroke: PANEL_COLORS.muted, strokeDasharray: '3 3' }}
                contentStyle={{ background: '#0c1715', border: `1px solid ${PANEL_COLORS.grid}`, borderRadius: 10 }}
                formatter={(value, name) => [
                  formatCompact(Number(Array.isArray(value) ? value[0] : value), 4),
                  String(name),
                ] as [string, string]}
                labelFormatter={(_, payload) => {
                  const point = payload?.[0]?.payload as PlotPoint | undefined;
                  return point?.design ? shortDesignId(point.design.design_id) : 'Landscape sample';
                }}
              />
              <Legend wrapperStyle={{ color: PANEL_COLORS.muted, fontSize: 10 }} />
              {landscapePoints.length > 0 ? (
                <Scatter name="Landscape" data={landscapePoints} fill={PANEL_COLORS.landscape} fillOpacity={0.22} isAnimationActive={false}>
                  {landscapePoints.map((point, index) => (
                    <Cell key={index} fill={point.feasible ? PANEL_COLORS.landscape : PANEL_COLORS.danger} fillOpacity={point.feasible ? 0.22 : 0.12} />
                  ))}
                </Scatter>
              ) : null}
              {paretoPoints.length > 1 ? (
                <Line
                  name="Pareto front"
                  data={paretoPoints}
                  dataKey="y"
                  stroke={PANEL_COLORS.agent}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  type="monotone"
                  isAnimationActive={false}
                />
              ) : null}
              <Scatter
                name="Designs"
                data={designPoints}
                isAnimationActive={false}
                onClick={(point) => {
                  const candidate = point as unknown as PlotPoint & { payload?: PlotPoint };
                  const selectedPoint = candidate.design ? candidate : candidate.payload;
                  if (selectedPoint?.design) onSelectDesign?.(selectedPoint.design);
                }}
              >
                {designPoints.map((point) => {
                  const design = point.design;
                  const selected = design?.design_id === selectedDesignId;
                  const baselineColor = design ? ORIGIN_COLORS[design.origin] : PANEL_COLORS.agent;
                  const color = design?.origin === 'agent' ? generationColor(design.generation) : baselineColor;
                  return (
                    <Cell
                      key={design?.design_id ?? `${point.x}-${point.y}`}
                      fill={point.feasible ? color : '#0c1715'}
                      stroke={selected ? '#ffffff' : color}
                      strokeWidth={selected ? 3 : point.feasible ? 1 : 2}
                      r={selected ? 6 : 4}
                      cursor={onSelectDesign ? 'pointer' : 'default'}
                    />
                  );
                })}
              </Scatter>
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </PanelFrame>
  );
}

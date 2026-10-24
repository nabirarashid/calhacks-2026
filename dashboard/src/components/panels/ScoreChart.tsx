import { useMemo } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { CurvePoint } from '@shared/contracts';
import { EmptyPanel, PANEL_COLORS, PanelFrame, formatCompact, safeNumber } from './panelPrimitives';

export type ScoreSeriesKey = 'agent' | 'cmaes' | 'random';

export interface BenchmarkBandPoint {
  evals: number;
  low: number;
  high: number;
}

export interface ScoreChartProps {
  curves?: Partial<Record<ScoreSeriesKey, CurvePoint[]>>;
  benchmarkBand?: BenchmarkBandPoint[];
  height?: number;
  className?: string;
}

interface ScoreDatum {
  evals: number;
  agent?: number;
  cmaes?: number;
  random?: number;
  benchmarkLow?: number;
  benchmarkRange?: number;
}

const seriesLabels: Record<ScoreSeriesKey, string> = {
  agent: 'Darwin agents',
  cmaes: 'CMA-ES',
  random: 'Random',
};

function bestSoFar(points: CurvePoint[]): CurvePoint[] {
  let best = Number.NEGATIVE_INFINITY;
  const byEval = new Map<number, number>();
  [...points]
    .filter((point) => Number.isFinite(point.evals) && Number.isFinite(point.best_aggregate))
    .sort((a, b) => a.evals - b.evals)
    .forEach((point) => {
      best = Math.max(best, point.best_aggregate);
      byEval.set(point.evals, best);
    });
  return [...byEval].map(([evals, best_aggregate]) => ({ evals, best_aggregate }));
}

export function ScoreChart({ curves = {}, benchmarkBand = [], height = 250, className }: ScoreChartProps) {
  const data = useMemo<ScoreDatum[]>(() => {
    const rows = new Map<number, ScoreDatum>();
    const normalizedCurves = {} as Partial<Record<ScoreSeriesKey, CurvePoint[]>>;
    (Object.keys(seriesLabels) as ScoreSeriesKey[]).forEach((key) => {
      const normalized = bestSoFar(curves[key] ?? []);
      normalizedCurves[key] = normalized;
      normalized.forEach((point) => {
        const row = rows.get(point.evals) ?? { evals: point.evals };
        row[key] = point.best_aggregate;
        rows.set(point.evals, row);
      });
    });
    benchmarkBand
      .filter((point) => Number.isFinite(point.evals) && Number.isFinite(point.low) && Number.isFinite(point.high))
      .forEach((point) => {
        const row = rows.get(point.evals) ?? { evals: point.evals };
        const low = Math.min(point.low, point.high);
        row.benchmarkLow = low;
        row.benchmarkRange = Math.abs(point.high - point.low);
        rows.set(point.evals, row);
      });
    const sorted = [...rows.values()].sort((a, b) => a.evals - b.evals);
    const latest: Partial<Record<ScoreSeriesKey, number>> = {};
    return sorted.map((row) => {
      (Object.keys(seriesLabels) as ScoreSeriesKey[]).forEach((key) => {
        const exact = normalizedCurves[key]?.find((point) => point.evals === row.evals);
        if (exact) latest[key] = exact.best_aggregate;
        if (latest[key] !== undefined) row[key] = latest[key];
      });
      return row;
    });
  }, [benchmarkBand, curves]);

  return (
    <PanelFrame title="Score vs. evaluations" eyebrow="Matched budget" className={className}>
      {data.length === 0 ? (
        <EmptyPanel label="Waiting for score data" detail="Agent and baseline curves will share the same evaluation axis." />
      ) : (
        <div className="px-2 pb-2 pt-3" style={{ height: Math.max(190, height) }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 2, left: -12 }}>
              <CartesianGrid stroke={PANEL_COLORS.grid} strokeDasharray="2 5" vertical={false} />
              <XAxis
                dataKey="evals"
                type="number"
                domain={['dataMin', 'dataMax']}
                allowDuplicatedCategory={false}
                tick={{ fill: PANEL_COLORS.muted, fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: PANEL_COLORS.grid }}
                label={{ value: 'evaluations', fill: PANEL_COLORS.muted, fontSize: 10, position: 'insideBottomRight' }}
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fill: PANEL_COLORS.muted, fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(value: number) => formatCompact(value, 2)}
              />
              <Tooltip
                cursor={{ stroke: PANEL_COLORS.muted, strokeDasharray: '3 3' }}
                contentStyle={{ background: '#0c1715', border: `1px solid ${PANEL_COLORS.grid}`, borderRadius: 10 }}
                labelStyle={{ color: PANEL_COLORS.text, fontFamily: 'monospace' }}
                formatter={(value, name) => [
                  formatCompact(safeNumber(Number(Array.isArray(value) ? value[0] : value)), 4),
                  String(name),
                ] as [string, string]}
              />
              <Legend wrapperStyle={{ color: PANEL_COLORS.muted, fontSize: 10, paddingTop: 8 }} />
              {benchmarkBand.length > 0 ? (
                <>
                  <Area dataKey="benchmarkLow" stackId="benchmark" stroke="none" fill="transparent" legendType="none" />
                  <Area
                    dataKey="benchmarkRange"
                    stackId="benchmark"
                    name="Benchmark range"
                    stroke="none"
                    fill={PANEL_COLORS.benchmark}
                    fillOpacity={0.16}
                    isAnimationActive={false}
                  />
                </>
              ) : null}
              {(Object.keys(seriesLabels) as ScoreSeriesKey[]).map((key) =>
                (curves[key]?.length ?? 0) > 0 ? (
                  <Line
                    key={key}
                    type="stepAfter"
                    dataKey={key}
                    name={seriesLabels[key]}
                    connectNulls
                    dot={false}
                    activeDot={{ r: 4, strokeWidth: 0 }}
                    stroke={PANEL_COLORS[key]}
                    strokeWidth={key === 'agent' ? 2.5 : 1.75}
                    isAnimationActive={false}
                  />
                ) : null,
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </PanelFrame>
  );
}

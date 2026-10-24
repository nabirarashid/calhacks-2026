import { useMemo, useState } from 'react';
import { scaleLinear, scalePoint } from 'd3-scale';
import { curveMonotoneX, line as makeLine } from 'd3-shape';
import type { DesignResult, ParamSpec, ParamValue } from '@shared/contracts';
import { EmptyPanel, ORIGIN_COLORS, PANEL_COLORS, PanelFrame, formatCompact, shortDesignId } from './panelPrimitives';

export interface ParallelCoordinatesProps {
  designs?: DesignResult[];
  parameters?: ParamSpec[];
  parameterNames?: string[];
  selectedDesignId?: string | null;
  onSelectDesign?: (design: DesignResult) => void;
  maxLines?: number;
  height?: number;
  className?: string;
}

interface AxisInfo {
  name: string;
  spec?: ParamSpec;
  numeric: boolean;
  domain: [number, number];
  choices: string[];
}

const WIDTH = 820;
const PAD_X = 54;
const PAD_TOP = 42;
const PAD_BOTTOM = 34;

export function ParallelCoordinates({
  designs = [],
  parameters = [],
  parameterNames,
  selectedDesignId,
  onSelectDesign,
  maxLines = 160,
  height = 250,
  className,
}: ParallelCoordinatesProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const safeHeight = Math.max(200, height);
  const displayedDesigns = useMemo(() => {
    if (designs.length <= maxLines) return designs;
    const selected = designs.find((design) => design.design_id === selectedDesignId);
    const sampled = designs.filter((_, index) => index % Math.ceil(designs.length / maxLines) === 0).slice(0, maxLines);
    return selected && !sampled.includes(selected) ? [...sampled.slice(1), selected] : sampled;
  }, [designs, maxLines, selectedDesignId]);

  const axes = useMemo<AxisInfo[]>(() => {
    const names = parameterNames?.length
      ? parameterNames
      : parameters.length
        ? parameters.map((parameter) => parameter.name)
        : [...new Set(designs.flatMap((design) => Object.keys(design.params ?? {})))];
    return names.slice(0, 9).map((name) => {
      const spec = parameters.find((parameter) => parameter.name === name);
      const values = designs.map((design) => design.params?.[name]).filter((value): value is ParamValue => value !== undefined);
      const numericValues = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
      const numeric = spec?.kind !== 'choice' && numericValues.length === values.length && values.length > 0;
      const observedMin = numericValues.length ? Math.min(...numericValues) : 0;
      const observedMax = numericValues.length ? Math.max(...numericValues) : 1;
      const min = typeof spec?.min === 'number' ? spec.min : observedMin;
      const max = typeof spec?.max === 'number' ? spec.max : observedMax;
      const choices = [...new Set([...(spec?.choices ?? []), ...values.map(String)])];
      return { name, spec, numeric, domain: min === max ? [min - 0.5, max + 0.5] : [min, max], choices };
    });
  }, [designs, parameterNames, parameters]);

  const xScale = useMemo(
    () => scalePoint<string>().domain(axes.map((axis) => axis.name)).range([PAD_X, WIDTH - PAD_X]),
    [axes],
  );

  const yForValue = (axis: AxisInfo, value: ParamValue | undefined): number | null => {
    if (value === undefined) return null;
    if (axis.numeric && typeof value === 'number' && Number.isFinite(value)) {
      return scaleLinear().domain(axis.domain).range([safeHeight - PAD_BOTTOM, PAD_TOP]).clamp(true)(value);
    }
    const index = axis.choices.indexOf(String(value));
    if (index < 0) return null;
    return scaleLinear().domain([0, Math.max(1, axis.choices.length - 1)]).range([safeHeight - PAD_BOTTOM, PAD_TOP])(index);
  };

  const pathForDesign = (design: DesignResult): string | null => {
    const coordinates = axes.flatMap((axis) => {
      const x = xScale(axis.name);
      const y = yForValue(axis, design.params?.[axis.name]);
      return x === undefined || y === null ? [] : [{ x, y }];
    });
    if (coordinates.length < 2) return null;
    return makeLine<{ x: number; y: number }>()
      .x((point) => point.x)
      .y((point) => point.y)
      .curve(curveMonotoneX)(coordinates);
  };

  const orderedDesigns = [...displayedDesigns].sort((a, b) => {
    const aActive = a.design_id === selectedDesignId || a.design_id === hoveredId;
    const bActive = b.design_id === selectedDesignId || b.design_id === hoveredId;
    return Number(aActive) - Number(bActive);
  });
  const hovered = designs.find((design) => design.design_id === hoveredId);

  return (
    <PanelFrame title="Parameter trade space" eyebrow={`${designs.length} designs`} className={className}>
      {designs.length === 0 || axes.length < 2 ? (
        <EmptyPanel label="Waiting for parameter data" detail="Parallel coordinates compare every evaluated design." />
      ) : (
        <div className="relative overflow-x-auto">
          <svg
            viewBox={`0 0 ${WIDTH} ${safeHeight}`}
            role="img"
            aria-label="Parallel coordinates parameter plot"
            className="block min-w-[620px] w-full"
            style={{ height: safeHeight }}
          >
            {axes.map((axis) => {
              const x = xScale(axis.name) ?? 0;
              const unit = axis.spec?.unit ? ` (${axis.spec.unit})` : '';
              const bottomLabel = axis.numeric ? formatCompact(axis.domain[0]) : axis.choices[0] ?? '—';
              const topLabel = axis.numeric ? formatCompact(axis.domain[1]) : axis.choices[axis.choices.length - 1] ?? '—';
              return (
                <g key={axis.name}>
                  <line x1={x} x2={x} y1={PAD_TOP} y2={safeHeight - PAD_BOTTOM} stroke={PANEL_COLORS.grid} strokeWidth="1" />
                  <text x={x} y={18} textAnchor="middle" fill={PANEL_COLORS.text} fontSize="9.5" fontFamily="monospace">
                    {axis.name.length > 15 ? `${axis.name.slice(0, 14)}…` : axis.name}
                  </text>
                  <text x={x} y={30} textAnchor="middle" fill={PANEL_COLORS.muted} fontSize="8">{unit}</text>
                  <text x={x} y={PAD_TOP - 4} textAnchor="middle" fill={PANEL_COLORS.muted} fontSize="8">{topLabel}</text>
                  <text x={x} y={safeHeight - 12} textAnchor="middle" fill={PANEL_COLORS.muted} fontSize="8">{bottomLabel}</text>
                </g>
              );
            })}
            {orderedDesigns.map((design) => {
              const path = pathForDesign(design);
              if (!path) return null;
              const active = design.design_id === selectedDesignId || design.design_id === hoveredId;
              const color = ORIGIN_COLORS[design.origin] ?? PANEL_COLORS.agent;
              return (
                <path
                  key={design.design_id}
                  d={path}
                  fill="none"
                  stroke={color}
                  strokeWidth={active ? 3 : 1}
                  strokeOpacity={active ? 1 : design.score?.feasible ? 0.24 : 0.12}
                  strokeDasharray={design.score?.feasible ? undefined : '3 3'}
                  className={onSelectDesign ? 'cursor-pointer' : ''}
                  onMouseEnter={() => setHoveredId(design.design_id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onClick={() => onSelectDesign?.(design)}
                >
                  <title>{`${shortDesignId(design.design_id)} · ${formatCompact(design.score?.aggregate ?? 0, 4)}`}</title>
                </path>
              );
            })}
          </svg>
          {hovered ? (
            <div className="pointer-events-none absolute right-3 top-3 rounded-lg border border-line bg-ink/95 px-3 py-2 text-xs shadow-xl">
              <span className="font-mono text-[10px] text-slate-500">{shortDesignId(hovered.design_id)}</span>
              <span className="ml-2 font-semibold text-mint">{formatCompact(hovered.score?.aggregate ?? 0, 4)}</span>
            </div>
          ) : null}
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-[10px] text-slate-500">
            {(Object.keys(ORIGIN_COLORS) as Array<keyof typeof ORIGIN_COLORS>).map((origin) => (
              designs.some((design) => design.origin === origin) ? (
                <span key={origin} className="inline-flex items-center gap-1.5"><i className="h-1.5 w-3 rounded-full" style={{ background: ORIGIN_COLORS[origin] }} />{origin.replace('baseline_', '')}</span>
              ) : null
            ))}
          </div>
        </div>
      )}
    </PanelFrame>
  );
}

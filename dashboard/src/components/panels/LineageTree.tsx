import { useMemo, useState } from 'react';
import type { DesignResult } from '@shared/contracts';
import { clamp, EmptyPanel, ORIGIN_COLORS, PANEL_COLORS, PanelFrame, formatCompact, shortDesignId } from './panelPrimitives';

export interface LineageTreeProps {
  designs?: DesignResult[];
  championId?: string | null;
  selectedDesignId?: string | null;
  onSelectDesign?: (design: DesignResult) => void;
  height?: number;
  className?: string;
}

interface PositionedDesign {
  design: DesignResult;
  x: number;
  y: number;
  radius: number;
}

interface Edge {
  parent: PositionedDesign;
  child: PositionedDesign;
  highlighted: boolean;
}

const WIDTH = 920;
const X_PAD = 50;
const Y_PAD_TOP = 44;
const Y_PAD_BOTTOM = 24;

export function LineageTree({
  designs = [],
  championId,
  selectedDesignId,
  onSelectDesign,
  height = 250,
  className,
}: LineageTreeProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const safeHeight = Math.max(200, height);

  const { nodes, edges, generations, ancestry } = useMemo(() => {
    const validDesigns = designs.filter((design) => design?.design_id && Number.isFinite(design.generation));
    const generations = [...new Set(validDesigns.map((design) => design.generation))].sort((a, b) => a - b);
    const xForGeneration = (generation: number) => {
      if (generations.length === 1) return WIDTH / 2;
      const index = Math.max(0, generations.indexOf(generation));
      const denominator = Math.max(1, generations.length - 1);
      return X_PAD + (index / denominator) * (WIDTH - X_PAD * 2);
    };
    const aggregates = validDesigns
      .map((design) => design.score?.aggregate)
      .filter((aggregate): aggregate is number => typeof aggregate === 'number' && Number.isFinite(aggregate));
    const minAggregate = aggregates.length ? Math.min(...aggregates) : 0;
    const maxAggregate = aggregates.length ? Math.max(...aggregates) : 1;
    const aggregateSpan = Math.max(1e-9, maxAggregate - minAggregate);
    const nodes: PositionedDesign[] = [];

    generations.forEach((generation) => {
      const column = validDesigns
        .filter((design) => design.generation === generation)
        .sort((a, b) => (b.score?.aggregate ?? -Infinity) - (a.score?.aggregate ?? -Infinity));
      column.forEach((design, index) => {
        const yRange = safeHeight - Y_PAD_TOP - Y_PAD_BOTTOM;
        const y = Y_PAD_TOP + ((index + 0.5) / Math.max(1, column.length)) * yRange;
        const scorePosition = clamp(((design.score?.aggregate ?? minAggregate) - minAggregate) / aggregateSpan);
        nodes.push({ design, x: xForGeneration(generation), y, radius: 4.5 + scorePosition * 4 });
      });
    });

    const byId = new Map(nodes.map((node) => [node.design.design_id, node]));
    const focusId = selectedDesignId ?? championId ?? null;
    const ancestry = new Set<string>();
    const visit = (id: string) => {
      if (ancestry.has(id)) return;
      ancestry.add(id);
      byId.get(id)?.design.parent_ids?.forEach(visit);
    };
    if (focusId) visit(focusId);

    const edges: Edge[] = [];
    nodes.forEach((child) => {
      child.design.parent_ids?.forEach((parentId) => {
        const parent = byId.get(parentId);
        if (parent) edges.push({ parent, child, highlighted: ancestry.has(parentId) && ancestry.has(child.design.design_id) });
      });
    });
    return { nodes, edges, generations, ancestry };
  }, [championId, designs, safeHeight, selectedDesignId]);

  const hovered = nodes.find((node) => node.design.design_id === hoveredId);

  return (
    <PanelFrame
      title="Design lineage"
      eyebrow={generations.length ? `${generations.length} generations · ${nodes.length} designs` : 'Evolution map'}
      className={className}
    >
      {nodes.length === 0 ? (
        <EmptyPanel label="No lineage yet" detail="Parent relationships appear as soon as designs are evaluated." />
      ) : (
        <div className="relative overflow-x-auto">
          <svg
            viewBox={`0 0 ${WIDTH} ${safeHeight}`}
            role="img"
            aria-label="Design lineage by generation"
            className="block min-w-[640px] w-full"
            style={{ height: safeHeight }}
          >
            <defs>
              <filter id="lineage-glow" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="2.5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>
            {generations.map((generation, index) => {
              const x = generations.length === 1
                ? WIDTH / 2
                : X_PAD + (index / (generations.length - 1)) * (WIDTH - X_PAD * 2);
              return (
                <g key={generation}>
                  <line x1={x} x2={x} y1={30} y2={safeHeight - 8} stroke={PANEL_COLORS.grid} strokeDasharray="2 6" />
                  <text x={x} y={20} textAnchor="middle" fill={PANEL_COLORS.muted} fontSize="10" fontFamily="monospace">
                    GEN {generation}
                  </text>
                </g>
              );
            })}
            {edges.map(({ parent, child, highlighted }) => {
              const dx = Math.max(20, (child.x - parent.x) * 0.48);
              return (
                <path
                  key={`${parent.design.design_id}-${child.design.design_id}`}
                  d={`M ${parent.x} ${parent.y} C ${parent.x + dx} ${parent.y}, ${child.x - dx} ${child.y}, ${child.x} ${child.y}`}
                  fill="none"
                  stroke={highlighted ? PANEL_COLORS.agent : PANEL_COLORS.grid}
                  strokeWidth={highlighted ? 2.2 : 1}
                  strokeOpacity={highlighted ? 0.92 : 0.65}
                  filter={highlighted ? 'url(#lineage-glow)' : undefined}
                />
              );
            })}
            {nodes.map((node) => {
              const { design, x, y, radius } = node;
              const selected = design.design_id === selectedDesignId;
              const isChampion = design.design_id === championId;
              const highlighted = ancestry.has(design.design_id);
              const color = ORIGIN_COLORS[design.origin] ?? PANEL_COLORS.agent;
              return (
                <g
                  key={design.design_id}
                  transform={`translate(${x} ${y})`}
                  className={onSelectDesign ? 'cursor-pointer' : ''}
                  role="button"
                  tabIndex={0}
                  aria-label={`${shortDesignId(design.design_id)}, aggregate ${formatCompact(design.score?.aggregate ?? 0, 3)}`}
                  onClick={() => onSelectDesign?.(design)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') onSelectDesign?.(design);
                  }}
                  onMouseEnter={() => setHoveredId(design.design_id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onFocus={() => setHoveredId(design.design_id)}
                  onBlur={() => setHoveredId(null)}
                >
                  {(selected || isChampion) ? (
                    <circle r={radius + 4} fill="none" stroke={selected ? '#fff' : PANEL_COLORS.agent} strokeWidth="1.5" opacity="0.85" />
                  ) : null}
                  <circle
                    r={radius}
                    fill={design.score?.feasible ? color : '#0c1715'}
                    fillOpacity={highlighted ? 1 : 0.7}
                    stroke={color}
                    strokeWidth={design.score?.feasible ? 1.5 : 2.5}
                    filter={highlighted ? 'url(#lineage-glow)' : undefined}
                  >
                    <title>{`${shortDesignId(design.design_id)} · ${design.operator} · ${formatCompact(design.score?.aggregate ?? 0, 4)}`}</title>
                  </circle>
                </g>
              );
            })}
          </svg>
          {hovered ? (
            <div
              className="pointer-events-none absolute z-10 w-56 rounded-xl border border-line bg-ink/95 p-3 text-xs shadow-2xl"
              style={{
                left: `${clamp(hovered.x / WIDTH, 0.1, 0.72) * 100}%`,
                top: `${clamp(hovered.y / safeHeight, 0.2, 0.66) * 100}%`,
              }}
            >
              <div className="flex items-center justify-between gap-2 font-mono text-[10px] text-slate-500">
                <span>{shortDesignId(hovered.design.design_id)}</span>
                <span className={hovered.design.score?.feasible ? 'text-mint' : 'text-coral'}>
                  {hovered.design.score?.feasible ? 'FEASIBLE' : 'INFEASIBLE'}
                </span>
              </div>
              <div className="mt-1 font-semibold text-slate-100">{hovered.design.operator} · {formatCompact(hovered.design.score?.aggregate ?? 0, 4)}</div>
              {hovered.design.rationale ? <p className="mt-1.5 line-clamp-3 leading-relaxed text-slate-400">{hovered.design.rationale}</p> : null}
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px] text-slate-500">
                {Object.entries(hovered.design.params ?? {}).slice(0, 6).map(([name, value]) => (
                  <span key={name} className="truncate">{name}: <b className="text-slate-300">{String(value)}</b></span>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </PanelFrame>
  );
}

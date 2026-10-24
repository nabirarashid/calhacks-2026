import type { ReactNode } from 'react';

export const PANEL_COLORS = {
  agent: '#70f0b6',
  cmaes: '#52d3ff',
  random: '#ffbd66',
  benchmark: '#7d8c88',
  grid: '#22322e',
  text: '#d6e4df',
  muted: '#7f918c',
  danger: '#ff806d',
  landscape: '#566762',
} as const;

export const AGENT_COLORS = {
  goal_parser: '#a78bfa',
  proposer: '#70f0b6',
  critic: '#ffbd66',
  strategist: '#52d3ff',
  reporter: '#f472b6',
  system: '#94a3b8',
} as const;

export const ORIGIN_COLORS = {
  seed: '#94a3b8',
  agent: PANEL_COLORS.agent,
  fallback: '#ff806d',
  baseline_cmaes: PANEL_COLORS.cmaes,
  baseline_random: PANEL_COLORS.random,
} as const;

export interface PanelFrameProps {
  title: string;
  eyebrow?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function PanelFrame({ title, eyebrow, action, children, className = '' }: PanelFrameProps) {
  return (
    <section
      className={`min-w-0 overflow-hidden rounded-2xl border border-line bg-panel/95 shadow-glow ${className}`}
      aria-label={title}
    >
      <header className="flex min-h-14 items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          {eyebrow ? (
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-mint/70">{eyebrow}</div>
          ) : null}
          <h2 className="truncate text-sm font-semibold tracking-tight text-slate-100">{title}</h2>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function EmptyPanel({ label, detail }: { label: string; detail?: string }) {
  return (
    <div className="flex min-h-44 flex-col items-center justify-center gap-2 px-6 text-center">
      <div className="h-1.5 w-1.5 rounded-full bg-mint/70 shadow-[0_0_14px_rgba(112,240,182,0.5)]" />
      <p className="text-sm text-slate-300">{label}</p>
      {detail ? <p className="max-w-xs text-xs leading-relaxed text-slate-500">{detail}</p> : null}
    </div>
  );
}

export function safeNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export function formatCompact(value: number, maximumFractionDigits = 2): string {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    notation: Math.abs(value) >= 10_000 ? 'compact' : 'standard',
    maximumFractionDigits,
  }).format(value);
}

export function shortDesignId(designId: string): string {
  const match = designId.match(/(g\d+-.+)$/);
  return match?.[1] ?? designId.slice(-12);
}

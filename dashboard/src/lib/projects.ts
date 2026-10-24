export type Maturity = 0 | 1 | 2 | 3 | 4;

export interface ProjectSummary {
  project_id: string;
  name: string;
  revision: number;
  maturity: Maturity;
  domain_pack?: string | null;
  /** Optional additive field used by the UI when the domain supplies a custom renderer. */
  renderer?: string | null;
}

export interface AnalysisProgressSnapshot {
  design_id: string;
  adapter_id: string;
  stage: 'export' | 'mesh' | 'solve' | 'parse' | 'converge';
  pct: number;
  elapsed_ms: number;
}

export const MATURITY_LABELS: Record<Maturity, string> = {
  0: 'Unsupported',
  1: 'Inventory-only',
  2: 'Manifest-reviewed',
  3: 'Solver-ready',
  4: 'Write-enabled',
};

export const MATURITY_PERMISSIONS: Record<Maturity, string> = {
  0: 'Explain blockers only',
  1: 'Inspect CAD and draft a manifest',
  2: 'Probe geometry and plan read-only work',
  3: 'Simulate and run bounded optimization',
  4: 'Apply an approved change, verify it, and create a version',
};

export function clampMaturity(value: unknown): Maturity {
  const parsed = typeof value === 'number' && Number.isFinite(value) ? Math.trunc(value) : 0;
  return Math.min(4, Math.max(0, parsed)) as Maturity;
}


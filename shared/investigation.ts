// Darwin contracts v1.2 — FROZEN mirror of shared/investigation.py (tag contracts-v1.2).
// Field names are snake_case exactly as on the wire. Python is the source of truth.
import type { GeometryRef, ParamValue } from './contracts';

export type Direction = 'up' | 'down' | 'flat';
export type Verdict = 'accepted' | 'rejected' | 'pivot';

export interface Prediction {
  metric: string;
  direction: Direction;
  pct_low: number;                     // expected % change vs the current design
  pct_high: number;
}

export interface Hypothesis {
  step: number;
  levers: string[];                    // 1-2 editable params
  candidates: Array<Record<string, ParamValue>>;   // 1-4 full param dicts
  principle_ids: string[];             // [] = exploratory
  rationale: string;
  predictions: Prediction[];
  source: 'llm' | 'rules';
}

export interface PredictionCheck {
  metric: string;
  predicted: Prediction;
  actual_pct: number;
  direction_ok: boolean;
  in_range: boolean;
  score: number;                       // 1 in range, 0.5 direction only, 0 wrong
}

export interface StepResult {
  step: number;
  tested: string[];                    // design_ids
  best_id: string;
  deltas: Record<string, number>;      // % change vs current
  checks: PredictionCheck[];
  verdict: Verdict;                    // decided by code
  explanation: string;
  lesson: string;
}

export interface Belief { text: string; evidence_steps: number[]; principle_id?: string | null; }

export interface Notebook {
  beliefs: Belief[];
  lever_effects: Record<string, Record<string, number>>;   // param -> metric -> %/unit
  ruled_out: string[];
  accuracy: number[];                  // running mean prediction score per step
}

export interface DesignApplied { design_id: string; geometry: GeometryRef; version?: string | null; }

// ---- session REST bodies (PLAN.md B.6)
export interface InspectParam { name: string; unit: string; value: ParamValue; min?: number | null; max?: number | null; }
export interface InspectResponse { project_id: string; params: InspectParam[]; fixed: string[]; }
export interface StartSessionRequest { doc_url: string; prompt: string; max_sims?: number; max_steps?: number; }
export interface StartSessionResponse {
  run_id: string;
  project_id: string;
  goal: import('./contracts').Goal;
  editable: string[];
  fixed: string[];
}

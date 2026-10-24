import type { AnyDarwinEvent } from '@shared/contracts';
import type { AnalysisProgressSnapshot } from '@/lib/projects';

export interface AnalysisProgressEvent {
  v: 1;
  type: 'analysis_progress';
  run_id: string;
  seq: number;
  ts: number;
  payload: AnalysisProgressSnapshot;
}

/** Additive v2 dashboard event union while the shared contract is owned by W-C. */
export type DashboardEvent = AnyDarwinEvent | AnalysisProgressEvent;


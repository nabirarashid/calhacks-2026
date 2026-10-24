import type {
  BudgetStatus,
  DesignSpace,
  GeometryRef,
  Goal,
  HealthResponse,
  Preset,
  RunConfig,
  RunSummary,
} from '@shared/contracts';
import type { ProjectSummary } from './projects';
import type {
  ActivationResult,
  CapabilityReportData,
  DroidDraftResult,
  OnboardingInspection,
  ProbeResult,
  ProjectManifestDraft,
  ReviewSubmission,
} from '@/onboarding';

export type CommitValue = string | number | boolean | null;

export interface CommitParamDiff {
  name: string;
  before?: CommitValue;
  after?: CommitValue;
}

export interface CommitPreview {
  target: string | Record<string, unknown>;
  param_diff: CommitParamDiff[] | Record<string, unknown>;
  expected_calls: number | string[] | Record<string, number>;
  checks_planned: Array<string | Record<string, unknown>>;
  maturity?: number;
}

export interface ApprovalRecord {
  status: string;
  run_id?: string;
  design_id?: string;
  param_hash?: string;
  approved_by?: string;
  approved_at?: string;
}

/**
 * The write result is additive to the legacy GeometryRef response.  The fields
 * are optional so an older backend can still be parsed, but the UI treats any
 * missing verification evidence as an incomplete/failed commit.
 */
export interface CommitResult extends Omit<Partial<GeometryRef>, 'status'> {
  status?: GeometryRef['status'] | 'partial' | 'blocked';
  geometry?: GeometryRef;
  geometry_ref?: GeometryRef;
  written_values?: Record<string, unknown>;
  written?: Record<string, unknown>;
  applied_values?: Record<string, unknown>;
  read_back?: Record<string, unknown>;
  readback?: Record<string, unknown>;
  verified_values?: Record<string, unknown>;
  geometry_check?: { passed?: boolean | null; detail?: string; status?: string };
  verification?: { geometry?: { passed?: boolean | null; detail?: string; status?: string } };
  version_name?: string;
  version?: { id?: string; name?: string };
  partial_write?: boolean;
  recovery_steps?: string[];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body
      ? { 'Content-Type': 'application/json', ...init.headers }
      : init?.headers,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  spaces: () => request<DesignSpace[]>('/api/design-spaces'),
  projects: () => request<ProjectSummary[]>('/api/projects'),
  presets: () => request<Preset[]>('/api/presets'),
  runs: () => request<RunSummary[]>('/api/runs'),
  budget: () => request<BudgetStatus>('/api/budget'),
  parseGoal: (text: string, designSpaceId: string, projectId?: string) =>
    request<Goal>('/api/goal/parse', {
      method: 'POST',
      body: JSON.stringify({ text, design_space_id: designSpaceId, ...(projectId ? { project_id: projectId } : {}) }),
    }),
  startRun: (goal: Goal, designSpaceId: string, config: Partial<RunConfig> = {}, projectId?: string) =>
    request<{ run_id: string }>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({ goal, design_space_id: designSpaceId, ...(projectId ? { project_id: projectId } : {}), config }),
    }),
  stopRun: (runId: string) => request<RunSummary>(`/api/runs/${runId}/stop`, { method: 'POST' }),
  replay: (recording: string, speed: number) =>
    request<{ run_id: string }>('/api/replay', {
      method: 'POST',
      body: JSON.stringify({ recording, speed }),
    }),
  events: async (runId: string) => {
    const response = await fetch(`/api/runs/${runId}/events`);
    if (!response.ok) throw new ApiError(`Could not load run events (${response.status})`, response.status);
    return response.text();
  },
  commitPreview: (runId: string) =>
    request<CommitPreview>(`/api/runs/${runId}/commit/preview`),
  commit: (runId: string, designId: string) =>
    request<CommitResult>(`/api/runs/${runId}/commit`, {
      method: 'POST',
      body: JSON.stringify({ design_id: designId }),
    }),
  approve: (runId: string, designId: string, approvedBy?: string) =>
    request<ApprovalRecord>(`/api/runs/${runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ design_id: designId, ...(approvedBy ? { approved_by: approvedBy } : {}) }),
    }),
  approval: (runId: string) => request<ApprovalRecord>(`/api/runs/${runId}/approve`),
  discover: (docUrl: string, probe: boolean) =>
    request<DesignSpace>('/api/discover', {
      method: 'POST',
      body: JSON.stringify({ doc_url: docUrl, probe }),
    }),
  inspectProject: (docUrl: string) =>
    request<OnboardingInspection>('/api/projects/inspect', {
      method: 'POST',
      body: JSON.stringify({ doc_url: docUrl }),
    }),
  reviewProject: ({ project_id, ...submission }: ReviewSubmission) =>
    request<ProjectManifestDraft>(`/api/projects/${encodeURIComponent(project_id)}/manifest`, {
      method: 'POST',
      body: JSON.stringify(submission),
    }),
  probeProject: (manifest: ProjectManifestDraft) =>
    request<ProbeResult[]>(`/api/projects/${encodeURIComponent(manifest.project_id)}/probe`, { method: 'POST' }),
  activateProject: (manifest: ProjectManifestDraft) =>
    request<ActivationResult>(`/api/projects/${encodeURIComponent(manifest.project_id)}/activate`, { method: 'POST' }),
  draftAdapter: (report: CapabilityReportData) =>
    request<DroidDraftResult>(`/api/projects/${encodeURIComponent(report.project_id)}/draft-adapter`, {
      method: 'POST',
      body: JSON.stringify({ capability_report: report, conformance_spec: 'solver-adapter-v2' }),
    }),
};

export async function downloadPrintPackage(runId: string, designId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ design_id: designId }),
  });
  if (!response.ok) throw new ApiError(`Print export failed (${response.status})`, response.status);
  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? `${designId}-print.zip`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

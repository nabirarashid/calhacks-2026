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
import type {
  InspectResponse,
  Notebook,
  StartSessionRequest,
  StartSessionResponse,
} from '@shared/investigation';

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
  presets: () => request<Preset[]>('/api/presets'),
  runs: () => request<RunSummary[]>('/api/runs'),
  budget: () => request<BudgetStatus>('/api/budget'),
  parseGoal: (text: string, designSpaceId: string) =>
    request<Goal>('/api/goal/parse', {
      method: 'POST',
      body: JSON.stringify({ text, design_space_id: designSpaceId }),
    }),
  startRun: (goal: Goal, designSpaceId: string, config: Partial<RunConfig> = {}) =>
    request<{ run_id: string }>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({ goal, design_space_id: designSpaceId, config }),
    }),
  stopRun: (runId: string) => request<RunSummary>(`/api/runs/${runId}/stop`, { method: 'POST' }),
  inspect: (docUrl: string) =>
    request<InspectResponse>('/api/inspect', {
      method: 'POST',
      body: JSON.stringify({ doc_url: docUrl }),
    }),
  startSession: (body: StartSessionRequest) =>
    request<StartSessionResponse>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  sessionNotebook: (runId: string) =>
    request<Notebook>(`/api/sessions/${runId}/notebook`),
  stopSession: (runId: string) =>
    request<RunSummary>(`/api/sessions/${runId}/stop`, { method: 'POST' }),
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
  commit: (runId: string, designId: string) =>
    request<GeometryRef>(`/api/runs/${runId}/commit`, {
      method: 'POST',
      body: JSON.stringify({ design_id: designId }),
    }),
  approve: (runId: string, designId: string, approvedBy?: string) =>
    request<{ status: string }>(`/api/runs/${runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ design_id: designId, ...(approvedBy ? { approved_by: approvedBy } : {}) }),
    }),
  discover: (docUrl: string, probe: boolean) =>
    request<DesignSpace>('/api/discover', {
      method: 'POST',
      body: JSON.stringify({ doc_url: docUrl, probe }),
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

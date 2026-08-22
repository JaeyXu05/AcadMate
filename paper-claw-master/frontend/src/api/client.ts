import { toApiError } from './errors';
import type {
  AgentMessageRequest,
  AgentMessageResponse,
  AgentStreamEvent,
  ApprovalRequest,
  ArtifactRead,
  PaperDetail,
  PaperSummary,
  ReportRead,
  ReportSummary,
  RunEventRead,
  RunRead,
  RuntimeSettingsRead,
  ArxivTaskDailyConfigRead,
  ArxivTaskDailyConfigUpdateRequest,
  ArxivTaskHarvestJobRead,
  ArxivTaskHistoryJobCreateRequest,
  ArxivTaskPaperRead,
  ArxivTaskQueryWindowRead,
  ArxivTaskStatusRead,
  ArxivTaskSubscriptionCreateRequest,
  ArxivTaskSubscriptionRead,
  ArxivTaskSubscriptionTestRead,
  ArxivTaskSubscriptionTestRequest,
  ArxivTaskSubscriptionUpdateRequest,
  MemoryRead,
  ThreadDetail,
  ThreadSummary,
  UploadArtifactRequest,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response.json() as Promise<T>;
}

async function requestJsonWithTimeout<T>(path: string, init: RequestInit | undefined, timeoutMs: number, timeoutMessage: string): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await requestJson<T>(path, { ...init, signal: controller.signal });
  } catch (caught) {
    if (caught instanceof Error && caught.name === 'AbortError') {
      throw new Error(timeoutMessage);
    }
    throw caught;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function streamNdjson<T>(response: Response, onEvent: (event: T) => void): Promise<T | null> {
  if (!response.body) {
    return null;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let lastEvent: T | null = null;

  const parseLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    const event = JSON.parse(trimmed) as T;
    lastEvent = event;
    onEvent(event);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      parseLine(line);
    }
  }
  buffer += decoder.decode();
  parseLine(buffer);
  return lastEvent;
}

export const api = {
  health: () => requestJson<{ status: string }>('/api/health'),

  listThreads: () => requestJson<ThreadSummary[]>('/api/threads', { cache: 'no-store' }),
  getThread: (threadId: number) => requestJson<ThreadDetail>(`/api/threads/${threadId}`, { cache: 'no-store' }),
  archiveThread: (threadId: number) => requestJson<ThreadSummary>(`/api/threads/${threadId}/archive`, { method: 'POST' }),
  listMemories: () => requestJson<MemoryRead[]>('/api/memories'),
  getRuntimeSettings: () => requestJson<RuntimeSettingsRead>('/api/settings/runtime'),

  getRun: (runId: number) => requestJson<RunRead>(`/api/runs/${runId}`, { cache: 'no-store' }),
  listRunEvents: (runId: number, afterSequence?: number) => {
    const suffix = afterSequence === undefined ? '' : `?after_sequence=${afterSequence}`;
    return requestJson<RunEventRead[]>(`/api/agent/runs/${runId}/events${suffix}`);
  },
  sendAgentMessage: (request: AgentMessageRequest) =>
    requestJson<AgentMessageResponse>('/api/agent/messages', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  sendAgentMessageStream: async (
    request: AgentMessageRequest,
    onEvent: (event: AgentStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<AgentMessageResponse> => {
    const response = await fetch(`${API_BASE_URL}/api/agent/messages/stream`, {
      method: 'POST',
      body: JSON.stringify(request),
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    });
    if (!response.ok) {
      throw await toApiError(response);
    }
    const finalEvent = await streamNdjson<AgentStreamEvent>(response, onEvent);
    if (!finalEvent) {
      throw new Error('Agent stream ended without events');
    }
    return {
      thread_id: finalEvent.thread_id,
      run_id: finalEvent.run_id,
      assistant_message_id: finalEvent.assistant_message_id ?? null,
      status: finalEvent.status ?? 'failed',
      message: finalEvent.message ?? null,
      error: finalEvent.error ?? null,
    };
  },
  cancelRun: (runId: number) => requestJson<RunRead>(`/api/agent/runs/${runId}/cancel`, { method: 'POST' }),
  submitRunApproval: (runId: number, request: ApprovalRequest) =>
    requestJson<RunRead>(`/api/agent/runs/${runId}/approval`, {
      method: 'POST',
      body: JSON.stringify(request),
    }),

  listPapers: () => requestJson<PaperSummary[]>('/api/papers'),
  getPaper: (paperId: number) => requestJson<PaperDetail>(`/api/papers/${paperId}`),

  listReports: () => requestJson<ReportSummary[]>('/api/reports'),
  getReport: (reportId: number) => requestJson<ReportRead>(`/api/reports/${reportId}`),
  deleteReport: (reportId: number) => fetch(`${API_BASE_URL}/api/reports/${reportId}`, { method: 'DELETE' }).then(async (response) => {
    if (!response.ok) {
      throw await toApiError(response);
    }
  }),

  getArtifact: (artifactId: number) => requestJson<ArtifactRead>(`/api/artifacts/${artifactId}`),
  uploadPaperArtifact: (paperId: number, request: UploadArtifactRequest) => {
    const formData = new FormData();
    formData.append('file', request.file);
    formData.append('role', request.role);
    if (request.runId != null) {
      formData.append('run_id', String(request.runId));
    }
    return requestJson<ArtifactRead>(`/api/papers/${paperId}/artifacts/upload`, {
      method: 'POST',
      body: formData,
    });
  },

  getArxivTaskStatus: () => requestJson<ArxivTaskStatusRead>('/api/tasks/arxiv/status', { cache: 'no-store' }),
  getArxivTaskDailyConfig: () => requestJson<ArxivTaskDailyConfigRead>('/api/tasks/arxiv/daily-config', { cache: 'no-store' }),
  updateArxivTaskDailyConfig: (request: ArxivTaskDailyConfigUpdateRequest) =>
    requestJson<ArxivTaskDailyConfigRead>('/api/tasks/arxiv/daily-config', {
      method: 'PUT',
      body: JSON.stringify(request),
    }),
  listArxivTaskSubscriptions: () => requestJson<ArxivTaskSubscriptionRead[]>('/api/tasks/arxiv/subscriptions', { cache: 'no-store' }),
  testArxivTaskSubscriptionQuery: (request: ArxivTaskSubscriptionTestRequest) =>
    requestJsonWithTimeout<ArxivTaskSubscriptionTestRead>('/api/tasks/arxiv/subscriptions/test-query', {
      method: 'POST',
      body: JSON.stringify(request),
    }, 55000, 'arXiv query test timed out. Refine the query and try again.'),
  createArxivTaskSubscription: (request: ArxivTaskSubscriptionCreateRequest) =>
    requestJson<ArxivTaskSubscriptionRead>('/api/tasks/arxiv/subscriptions', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  updateArxivTaskSubscription: (subscriptionId: number, request: ArxivTaskSubscriptionUpdateRequest) =>
    requestJson<ArxivTaskSubscriptionRead>(`/api/tasks/arxiv/subscriptions/${subscriptionId}`, {
      method: 'PUT',
      body: JSON.stringify(request),
    }),
  deleteArxivTaskSubscription: (subscriptionId: number) =>
    requestJson<{ ok: boolean }>(`/api/tasks/arxiv/subscriptions/${subscriptionId}`, { method: 'DELETE' }),
  runArxivTaskDailyNow: () => requestJson<ArxivTaskHarvestJobRead>('/api/tasks/arxiv/daily/run', { method: 'POST' }),
  createArxivTaskHistoryJob: (request: ArxivTaskHistoryJobCreateRequest) =>
    requestJson<ArxivTaskHarvestJobRead>('/api/tasks/arxiv/history-jobs', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  startArxivTaskHistoryJob: (jobId: number) => requestJson<ArxivTaskHarvestJobRead>(`/api/tasks/arxiv/history-jobs/${jobId}/start`, { method: 'POST' }),
  pauseArxivTaskHistoryJob: (jobId: number) => requestJson<ArxivTaskHarvestJobRead>(`/api/tasks/arxiv/history-jobs/${jobId}/pause`, { method: 'POST' }),
  stopArxivTaskHistoryJob: (jobId: number) => requestJson<ArxivTaskHarvestJobRead>(`/api/tasks/arxiv/history-jobs/${jobId}/stop`, { method: 'POST' }),
  listArxivTaskWindows: (subscriptionId?: number | null, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (subscriptionId) {
      params.set('subscription_id', String(subscriptionId));
    }
    return requestJson<ArxivTaskQueryWindowRead[]>(`/api/tasks/arxiv/windows?${params.toString()}`, { cache: 'no-store' });
  },
  listArxivTaskPapers: (subscriptionId?: number | null, limit = 50, offset = 0, publishedStart?: string | null, publishedEnd?: string | null) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (subscriptionId) {
      params.set('subscription_id', String(subscriptionId));
    }
    if (publishedStart) {
      params.set('published_start', publishedStart);
    }
    if (publishedEnd) {
      params.set('published_end', publishedEnd);
    }
    return requestJson<ArxivTaskPaperRead[]>(`/api/tasks/arxiv/papers?${params.toString()}`, { cache: 'no-store' });
  },
};

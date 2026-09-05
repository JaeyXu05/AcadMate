import api, { emitApiSettingsRequired } from './axios';

export type ConversationSurface = 'search' | 'research';

export interface ConversationGoal {
  id: number;
  conversation_id: number;
  version: number;
  title: string;
  description: string;
  status: 'active' | 'paused' | 'completed' | 'superseded' | string;
  source: 'user' | 'suggestion' | string;
  created_at: string;
}

export interface ConversationMessage {
  id: number;
  role: 'user' | 'assistant' | 'system' | string;
  content: string;
  metadata?: Record<string, unknown>;
  created_at: string;
}

export interface ConversationSummary {
  id: number;
  project_id?: number | null;
  surface: ConversationSurface;
  title: string;
  status: string;
  active_goal_id?: number | null;
  agent_thread_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  active_goal?: ConversationGoal | null;
  goals: ConversationGoal[];
  messages: ConversationMessage[];
  metadata?: Record<string, unknown>;
}

export async function listConversations(params?: { surface?: ConversationSurface; projectId?: number }): Promise<ConversationSummary[]> {
  return (await api.get('/conversations', { params: { surface: params?.surface, project_id: params?.projectId } })).data;
}

export async function createConversation(input?: { surface?: ConversationSurface; title?: string; projectId?: number }): Promise<Conversation> {
  return (await api.post('/conversations', {
    surface: input?.surface || 'research',
    title: input?.title,
    project_id: input?.projectId,
  })).data;
}

export async function getConversation(id: number): Promise<Conversation> {
  return (await api.get(`/conversations/${id}`)).data;
}

export async function updateConversation(id: number, input: { title?: string; status?: string; project_id?: number | null }): Promise<Conversation> {
  return (await api.patch(`/conversations/${id}`, input)).data;
}

export async function createGoal(id: number, input: { title: string; description?: string; source?: 'user' | 'suggestion' }): Promise<ConversationGoal> {
  return (await api.post(`/conversations/${id}/goals`, input)).data;
}

export async function updateGoal(id: number, status: ConversationGoal['status']): Promise<ConversationGoal> {
  return (await api.patch(`/conversations/goals/${id}`, { status })).data;
}

export interface PaperClawStreamEvent {
  type?: string;
  thread_id?: number;
  run_id?: number;
  status?: string;
  message?: string;
  error?: string;
  payload?: Record<string, unknown>;
  event_type?: string;
  sequence?: number;
}

function token(): string {
  return localStorage.getItem('token') || sessionStorage.getItem('token') || '';
}

export async function streamConversationMessage(
  conversationId: number,
  message: string,
  onEvent: (event: PaperClawStreamEvent) => void,
  options?: { signal?: AbortSignal; activePaperId?: number; activePaperTitle?: string },
): Promise<void> {
  const response = await fetch(`/api/conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token()}`,
    },
    body: JSON.stringify({ message, active_paper_id: options?.activePaperId, active_paper_title: options?.activePaperTitle }),
    signal: options?.signal,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    let detail = body;
    try {
      const payload = JSON.parse(body) as { code?: unknown; message?: unknown; error?: unknown; action?: { path?: unknown } };
      if (response.status === 428 && payload.code === 'API_SETTINGS_REQUIRED') {
        emitApiSettingsRequired({
          message: typeof payload.message === 'string' ? payload.message : undefined,
          path: typeof payload.action?.path === 'string' ? payload.action.path : undefined,
        });
      }
      detail = [payload.message, payload.error].find((item) => typeof item === 'string' && item.trim()) as string || body;
    } catch { /* 非 JSON 错误正文原样保留 */ }
    throw new Error(detail || `请求失败（HTTP ${response.status}）`);
  }
  if (!response.body) throw new Error('响应体不可读');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const consume = (line: string) => {
    if (!line.trim()) return;
    try { onEvent(JSON.parse(line) as PaperClawStreamEvent); } catch { /* 忽略不完整事件 */ }
  };
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      lines.forEach(consume);
    }
    buffer += decoder.decode();
    consume(buffer);
  } finally {
    reader.releaseLock();
  }
}

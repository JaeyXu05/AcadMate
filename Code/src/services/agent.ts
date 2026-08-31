import type { SseEvent } from '../types/search';
import api from './axios';

export interface ChatWithAgentOptions {
  signal?: AbortSignal;
  resumeTraceId?: string | null;
  uploadId?: string | null;
}

export interface PaperReadResult {
  run_id?: string;
  thread_id?: number;
  skill_id?: string;
  status?: string;
  review_status?: string;
  evidence_refs?: string[];
  suggested_next_skill?: string | null;
  artifact?: {
    type?: string;
    paper_id?: number;
    candidate_id?: string;
    mentor_name?: string;
    selected_publication?: string;
    topics?: string[];
    publications?: unknown[];
    available_publications?: unknown[];
    retrieved_chunks?: Array<{
      evidence_id?: string;
      chunk_id?: number;
      score?: number;
      mode?: string;
      content?: string;
      cited?: boolean;
    }>;
    answer?: string;
    run_status?: string;
    review_status?: string;
    research_tasks?: unknown[];
    retry?: {
      skill_id?: string;
      reason?: string;
      target?: string;
      existing_api?: string;
      paper_id?: number;
    } | null;
    note?: string;
    error?: string;
  };
}

/**
 * 调用智能体对话接口（POST SSE）。
 * 使用 fetch + ReadableStream 逐行解析 SSE 事件，
 * 每次解析出一个完整事件时回调 onEvent。
 * 服务端会同时推 thinking（旧契约）与 stage（审核/返工时间轴）。
 */
export async function chatWithAgent(
  message: string,
  onEvent: (event: SseEvent) => void,
  options?: ChatWithAgentOptions,
): Promise<void> {
  const token =
    localStorage.getItem('token') || sessionStorage.getItem('token') || '';

  const res = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      message,
      resume_trace_id: options?.resumeTraceId || undefined,
      upload_id: options?.uploadId || undefined,
    }),
    signal: options?.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `请求失败 (${res.status})`);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error('响应体不可读');

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE 消息以 \n\n 分隔
      const parts = buffer.split('\n\n');
      // 最后一段可能不完整，保留
      buffer = parts.pop() ?? '';

      for (const part of parts) {
        const lines = part.split('\n');
        let eventType = '';
        let data = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            data = line.slice(6).trim();
          }
        }

        if (data) {
          try {
            const parsed = JSON.parse(data) as SseEvent;
            if (eventType) parsed.type = eventType as SseEvent['type'];
            onEvent(parsed);
            if (parsed.type === 'event' || parsed.type === 'stage') {
              await new Promise((r) => setTimeout(r, 40));
            }
          } catch {
            // 忽略无法解析的数据行
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/** 详情页「阅读其论文」：走 D 代理 → A Paper Skill，用语料 publications */
export async function readMentorPapers(
  candidateId: string,
  options?: { paperId?: number },
): Promise<PaperReadResult> {
  const { data } = await api.post<PaperReadResult>(
    '/agent/read',
    { candidate_id: candidateId, paper_id: options?.paperId },
    { timeout: 450000 },
  );
  return data;
}

export async function uploadPaperForRetry(input: {
  file: File;
  candidateId: string;
  paperId?: number;
  runId?: string;
}): Promise<{ paper_id: number; document_id?: string; retry?: { paper_id?: number } }> {
  const form = new FormData();
  form.append('file', input.file);
  form.append('candidate_id', input.candidateId);
  if (input.paperId) form.append('paper_id', String(input.paperId));
  if (input.runId) form.append('run_id', input.runId);
  const { data } = await api.post('/agent/paper-upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 450000,
  });
  return data;
}

export async function listAgentArtifacts(params?: { advisorId?: string; skillId?: string }) {
  const { data } = await api.get('/agent/artifacts', {
    params: { advisor_id: params?.advisorId, skill_id: params?.skillId },
  });
  return data;
}

/**
 * 生成一个随机的 session id
 */
export function generateSessionId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

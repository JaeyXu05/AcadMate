import type { SseEvent } from '../types/search';

/**
 * 调用智能体对话接口（POST SSE）。
 * 使用 fetch + ReadableStream 逐行解析 SSE 事件，
 * 每次解析出一个完整事件时回调 onEvent。
 */
export async function chatWithAgent(
  message: string,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token =
    localStorage.getItem('token') || sessionStorage.getItem('token') || '';

  const res = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
    signal,
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

/**
 * 生成一个随机的 session id
 */
export function generateSessionId(): string {
  return `session_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
/** 导师信息（临时定义，后续与爬虫同学对齐） */
export interface Advisor {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  /** H 指数（当前 RAG/A 后端均无真实值，暂留作备用；界面用 papers 论文数展示） */
  hIndex?: number;
  papers: number;
  matchScore: number;
  explanation?: string;
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  advisors?: Advisor[];
}

/** SSE 事件类型 */
export type SseEventType = 'thinking' | 'result' | 'summary' | 'done' | 'error';

/** SSE 事件载荷 */
export interface SseEvent {
  type: SseEventType;
  content?: string;
  advisors?: Advisor[];
  message?: string;
}

/** 排序方式 */
export type SortBy = 'match' | 'staffId' | 'papers' | 'department';
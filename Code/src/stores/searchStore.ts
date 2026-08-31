import { create } from 'zustand';
import type { Advisor, AgentStage, ChatMessage, RuntimeEvent, SortBy } from '../types/search';

let msgCounter = 0;
function genId(): string {
  msgCounter += 1;
  return `msg_${Date.now()}_${msgCounter}`;
}

/** 生成会话 id（用于 chat_history 分组） */
function genSessionId(): string {
  return `session_${Date.now()}_${msgCounter}`;
}

/** 分栏比例默认值 */
const DEFAULT_SPLIT_RATIO = 0.45;
/** localStorage key：记住拖拽分栏位置，跨会话保留 */
const SPLIT_RATIO_STORAGE_KEY = 'search_split_ratio';

function loadSplitRatio(): number {
  try {
    const raw = localStorage.getItem(SPLIT_RATIO_STORAGE_KEY);
    if (raw) {
      const r = parseFloat(raw);
      if (!Number.isNaN(r) && r > 0 && r < 1) return r;
    }
  } catch { /* ignore */ }
  return DEFAULT_SPLIT_RATIO;
}

function saveSplitRatio(ratio: number) {
  try {
    localStorage.setItem(SPLIT_RATIO_STORAGE_KEY, String(ratio));
  } catch { /* ignore */ }
}

interface SearchState {
  chatHistory: ChatMessage[];
  searchResults: Advisor[];
  sortBy: SortBy;
  isStreaming: boolean;
  /** 可拖拽分栏左侧占比（0-1），0.45 为默认值 */
  splitRatio: number;
  /** 当前对话会话 id（用于 chat_history 分组），addUserMessage 时惰性生成 */
  sessionId: string;
  /** 待恢复的检索/对话 query（由历史记录或云图联动写入，ChatWindow 消费后清空） */
  pendingQuery: string | null;
  /** Harness 建议的下一 Skill（有匹配导师且无阅读记录 → paper_qa） */
  suggestedNextSkill: string | null;
  /** 当前 Mentor 工作流 trace_id；澄清续跑必须复用，不能新开一轮 */
  activeTraceId: string | null;
  clarificationPending: boolean;
  lastRunId: string | null;
  /** Composer / 统一输入附带的 PDF upload_id（消费后清空） */
  pendingUploadId: string | null;

  /** 用户发送消息，同时创建空的 agent 占位消息 */
  addUserMessage: (text: string) => string;
  /** agent 消息逐 chunk 追加内容 */
  appendAgentChunk: (msgId: string, chunk: string) => void;
  /** 追加一条多智能体阶段（审核失败 / 返工等） */
  appendAgentStage: (msgId: string, stage: AgentStage) => void;
  appendAgentEvent: (msgId: string, ev: RuntimeEvent) => void;
  appendAgentThinking: (msgId: string, step: { agent?: string; text: string }) => void;
  setPendingUploadId: (id: string | null) => void;
  /** 标记 agent 消息流式完成，可选附带 advisor 结果 */
  setAgentMessageComplete: (msgId: string, advisors?: Advisor[], responseKind?: 'mentor' | 'chat') => void;
  setSuggestedNextSkill: (skill: string | null) => void;
  setWorkflowIdentity: (input: {
    traceId?: string | null;
    runId?: string | null;
    clarificationPending?: boolean;
  }) => void;
  /** 直接设置搜索结果列表 */
  setSearchResults: (advisors: Advisor[]) => void;
  /** 切换排序方式 */
  setSortBy: (sort: SortBy) => void;
  /** 记住拖拽分栏位置 */
  setSplitRatio: (ratio: number) => void;
  /** 设置待恢复 query（ChatWindow 监听并自动发送） */
  setPendingQuery: (q: string | null) => void;
  /** 清空当前对话 */
  clearChat: () => void;
}

export const useSearchStore = create<SearchState>((set, get) => ({
  chatHistory: [],
  searchResults: [],
  sortBy: 'match',
  isStreaming: false,
  splitRatio: loadSplitRatio(),
  sessionId: '',
  pendingQuery: null,
  suggestedNextSkill: null,
  activeTraceId: null,
  clarificationPending: false,
  lastRunId: null,
  pendingUploadId: null,

  addUserMessage: (text) => {
    let sessionId = get().sessionId;
    // 同一搜索页对话保持 session/thread；只有清空对话才开新会话，才能续跑澄清。
    if (!sessionId) {
      sessionId = genSessionId();
    }
    const userMsg: ChatMessage = {
      id: genId(),
      role: 'user',
      content: text,
      timestamp: Date.now(),
    };
    const agentMsg: ChatMessage = {
      id: genId(),
      role: 'agent',
      content: '',
      timestamp: Date.now(),
      isStreaming: true,
      stages: [],
      events: [],
      thinking: [],
    };
    set({
      sessionId,
      chatHistory: [...get().chatHistory, userMsg, agentMsg],
      isStreaming: true,
    });
    return agentMsg.id;
  },

  appendAgentChunk: (msgId, chunk) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId ? { ...m, content: m.content + chunk } : m,
      ),
    }));
  },

  appendAgentStage: (msgId, stage) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId
          ? { ...m, stages: [...(m.stages ?? []), stage] }
          : m,
      ),
    }));
  },

  appendAgentEvent: (msgId, ev) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId
          ? { ...m, events: [...(m.events ?? []), ev] }
          : m,
      ),
    }));
  },

  appendAgentThinking: (msgId, step) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId
          ? { ...m, thinking: [...(m.thinking ?? []), step] }
          : m,
      ),
    }));
  },

  setPendingUploadId: (id) => set({ pendingUploadId: id }),

  setSuggestedNextSkill: (skill) => set({ suggestedNextSkill: skill }),

  setWorkflowIdentity: ({ traceId, runId, clarificationPending }) =>
    set((state) => ({
      activeTraceId: traceId === undefined ? state.activeTraceId : traceId,
      lastRunId: runId === undefined ? state.lastRunId : runId,
      clarificationPending:
        clarificationPending === undefined ? state.clarificationPending : clarificationPending,
    })),

  setAgentMessageComplete: (msgId, advisors, responseKind) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId ? { ...m, isStreaming: false, ...(responseKind ? { responseKind } : {}) } : m,
      ),
      searchResults: advisors ?? state.searchResults,
      isStreaming: false,
    }));
  },

  setSearchResults: (advisors) => set({ searchResults: advisors }),

  setSortBy: (sortBy) => set({ sortBy }),

  setSplitRatio: (ratio) => {
    set({ splitRatio: ratio });
    saveSplitRatio(ratio);
  },

  setPendingQuery: (q) => set({ pendingQuery: q }),

  clearChat: () =>
    set({
      chatHistory: [],
      searchResults: [],
      isStreaming: false,
      sessionId: '',
      pendingQuery: null,
      suggestedNextSkill: null,
      activeTraceId: null,
      clarificationPending: false,
      lastRunId: null,
      pendingUploadId: null,
      // 注意：清空对话时不再重置分栏位置，保留用户记住的拖拽比例
    }),
}));

import { create } from 'zustand';
import type { Advisor, ChatMessage, SortBy } from '../types/search';

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

  /** 用户发送消息，同时创建空的 agent 占位消息 */
  addUserMessage: (text: string) => string;
  /** agent 消息逐 chunk 追加内容 */
  appendAgentChunk: (msgId: string, chunk: string) => void;
  /** 标记 agent 消息流式完成，可选附带 advisor 结果 */
  setAgentMessageComplete: (msgId: string, advisors?: Advisor[]) => void;
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

  addUserMessage: (text) => {
    let sessionId = get().sessionId;
    // 首次，或上一轮 agent 已结束（!isStreaming）后的新一轮 → 开新会话，
    // 便于后端按 session 分组、历史只显示每个会话的首条消息。
    if (!sessionId || !get().isStreaming) {
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

  setAgentMessageComplete: (msgId, advisors) => {
    set((state) => ({
      chatHistory: state.chatHistory.map((m) =>
        m.id === msgId ? { ...m, isStreaming: false } : m,
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
      // 注意：清空对话时不再重置分栏位置，保留用户记住的拖拽比例
    }),
}));
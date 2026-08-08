/** 用户信息 */
export interface User {
  id: number | string;
  email: string;
  nickname?: string;
  grade?: string;
  major?: string;
  interests?: string[];
  skills?: string[];
  bio?: string;
}

/** 登录请求参数 */
export interface LoginParams {
  email: string;
  password: string;
  rememberMe?: boolean;
}

/** 登录响应 */
export interface LoginResponse {
  token: string;
  user: User;
}

/** 收藏项 */
export interface FavoriteItem {
  id: number;
  advisor_id: string;
  created_at: string;
}

/** 用户设置（服务端同步） */
export interface ServerSettings {
  bg_theme: string;
  bg_color: string;
  default_sort: string;
  card_density: string;
}

// ===== 历史记录 =====

/** 单条历史记录 */
export interface HistoryItem {
  id: string;          // "search_123" 或 "chat_456"
  type: 'search' | 'chat';
  content: SearchHistoryContent | ChatHistoryContent;
  created_at: string;
}

export interface SearchHistoryContent {
  query: string;
  resultsCount: number;
}

export interface ChatHistoryContent {
  sessionId: string;
  firstMessage: string;
}

/** 分页响应 */
export interface HistoryPage {
  items: HistoryItem[];
  total: number;
  page: number;
  pageSize: number;
}
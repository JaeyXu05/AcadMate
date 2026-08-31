/** 科研成长状态（匹配 / 方向 / 已读论文） */
export interface GrowthMentor {
  id: string;
  name: string;
  tags?: string[];
  evidence_refs?: string[];
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthReadPaper {
  paper_id?: number;
  candidate_id: string;
  mentor_name?: string;
  titles: string[];
  read_at: string;
  evidence_refs?: string[];
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthExperience {
  id: string;
  type: string;
  summary: string;
  evidence_refs: string[];
  verified_at?: string;
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthArtifact {
  id: string;
  type: string;
  title: string;
  evidence_refs: string[];
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthResearchTask {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'blocked';
  acceptance_criteria: string[];
  evidence_refs?: string[];
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthDirectionHypothesis {
  id: string;
  direction: string;
  status: 'hypothesis' | 'supported' | 'rejected';
  evidence_refs: string[];
  updated_at?: string;
  source_run_id?: string;
  review_status?: string;
}

export interface GrowthState {
  matched_mentors: GrowthMentor[];
  directions: string[];
  read_papers: GrowthReadPaper[];
  verified_experiences: GrowthExperience[];
  artifacts: GrowthArtifact[];
  research_tasks: GrowthResearchTask[];
  direction_hypotheses: GrowthDirectionHypothesis[];
}

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

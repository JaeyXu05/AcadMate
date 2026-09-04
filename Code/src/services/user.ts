import api from './axios';
import type { FavoriteItem, GrowthState, ServerSettings, HistoryPage } from '../types/auth';

export type ResearchCapabilityLevel = 'seen' | 'understood' | 'implemented' | 'reproduced' | 'debugged' | 'experimented' | 'innovated' | 'unknown';

export interface ResearchProfile {
  type: 'research_profile';
  summary: string;
  capabilities: Array<{
    name: string;
    level: ResearchCapabilityLevel;
    assessment: string;
    evidence_status: 'self_reported' | 'reviewed' | 'unknown';
    evidence_refs: string[];
  }>;
  directions: Array<{
    name: string;
    status: 'interest' | 'hypothesis' | 'supported' | 'unknown';
    rationale: string;
    evidence_refs: string[];
  }>;
  gaps: Array<{ gap: string; why_it_matters: string; evidence_refs: string[] }>;
  next_actions: Array<{ action: string; deliverable: string; acceptance_criteria: string[]; evidence_refs: string[] }>;
  missing_information: string[];
  evidence_refs: string[];
  generated_at: string;
  review_status: string;
  source_signature?: string;
}

export interface ResearchProfileResponse {
  profile: ResearchProfile | null;
  stale: boolean;
}

// ===== 用户信息 =====

/** 更新用户信息 */
export async function updateProfile(profile: Record<string, unknown>): Promise<Record<string, unknown>> {
  const { data } = await api.put('/user/profile', profile);
  return data;
}

/** 注销账号（级联删除个人数据） */
export async function deleteAccount(): Promise<{ deleted: boolean }> {
  const { data } = await api.delete('/user/account');
  return data;
}

export function emptyGrowth(): GrowthState {
  return {
    matched_mentors: [],
    directions: [],
    read_papers: [],
    verified_experiences: [],
    artifacts: [],
    research_tasks: [],
    direction_hypotheses: [],
  };
}

/** 获取科研成长状态 */
export async function getGrowth(): Promise<GrowthState> {
  const { data } = await api.get<GrowthState>('/user/growth');
  return {
    matched_mentors: Array.isArray(data?.matched_mentors) ? data.matched_mentors : [],
    directions: Array.isArray(data?.directions) ? data.directions : [],
    read_papers: Array.isArray(data?.read_papers) ? data.read_papers : [],
    verified_experiences: Array.isArray(data?.verified_experiences) ? data.verified_experiences : [],
    artifacts: Array.isArray(data?.artifacts) ? data.artifacts : [],
    research_tasks: Array.isArray(data?.research_tasks) ? data.research_tasks : [],
    direction_hypotheses: Array.isArray(data?.direction_hypotheses) ? data.direction_hypotheses : [],
  };
}

export async function getResearchProfile(): Promise<ResearchProfileResponse> {
  const data = (await api.get<ResearchProfileResponse>('/user/research-profile')).data;
  return { profile: normalizeResearchProfile(data?.profile), stale: Boolean(data?.stale) };
}

export async function generateResearchProfile(): Promise<ResearchProfileResponse> {
  const data = (await api.post<ResearchProfileResponse>('/user/research-profile')).data;
  return { profile: normalizeResearchProfile(data?.profile), stale: Boolean(data?.stale) };
}

function normalizeResearchProfile(value: ResearchProfile | null | undefined): ResearchProfile | null {
  if (!value || value.type !== 'research_profile' || typeof value.summary !== 'string') return null;
  return {
    ...value,
    capabilities: Array.isArray(value.capabilities) ? value.capabilities : [],
    directions: Array.isArray(value.directions) ? value.directions : [],
    gaps: Array.isArray(value.gaps) ? value.gaps : [],
    next_actions: Array.isArray(value.next_actions) ? value.next_actions : [],
    missing_information: Array.isArray(value.missing_information) ? value.missing_information : [],
    evidence_refs: Array.isArray(value.evidence_refs) ? value.evidence_refs : [],
  };
}

// ===== 收藏夹 =====

/** 获取收藏列表 */
export async function getFavorites(): Promise<FavoriteItem[]> {
  const { data } = await api.get<FavoriteItem[]>('/favorites');
  return data;
}

/** 添加收藏 */
export async function addFavorite(advisor_id: string): Promise<FavoriteItem> {
  const { data } = await api.post<FavoriteItem>('/favorites', { advisor_id });
  return data;
}

/** 取消收藏 */
export async function removeFavorite(advisor_id: string): Promise<void> {
  await api.delete(`/favorites/${encodeURIComponent(advisor_id)}`);
}

// ===== 设置 =====

/** 获取用户设置 */
export async function getSettings(): Promise<ServerSettings> {
  const { data } = await api.get<ServerSettings>('/settings');
  return data;
}

/** 更新用户设置 */
export async function updateSettings(settings: Partial<ServerSettings>): Promise<ServerSettings> {
  const { data } = await api.put<ServerSettings>('/settings', settings);
  return data;
}

// ===== 历史记录 =====

/** 获取历史记录（分页） */
export async function getHistory(page = 1, pageSize = 20): Promise<HistoryPage> {
  const { data } = await api.get<HistoryPage>('/history', { params: { page, pageSize } });
  return data;
}

/** 删除单条历史记录（id 格式: "search_123" 或 "chat_456"） */
export async function deleteHistory(id: string): Promise<void> {
  await api.delete(`/history/${encodeURIComponent(id)}`);
}

/** 清空全部历史记录 */
export async function clearHistory(): Promise<{ deleted: number }> {
  const { data } = await api.delete('/history');
  return data;
}

/** 记录一次检索（写入 search_history） */
export async function recordSearch(
  query: string,
  resultsCount: number,
  meta?: { runId?: string; traceId?: string },
): Promise<void> {
  await api.post('/history/search', {
    query,
    results_count: resultsCount,
    run_id: meta?.runId,
    trace_id: meta?.traceId,
  });
}

/** 记录一条对话消息（写入 chat_history） */
export async function recordChat(sessionId: string, role: 'user' | 'agent', content: string): Promise<void> {
  await api.post('/history/chat', { session_id: sessionId, role, content });
}

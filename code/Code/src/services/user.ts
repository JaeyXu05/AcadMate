import api from './axios';
import type { FavoriteItem, ServerSettings, HistoryPage } from '../types/auth';

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
export async function recordSearch(query: string, resultsCount: number): Promise<void> {
  await api.post('/history/search', { query, results_count: resultsCount });
}

/** 记录一条对话消息（写入 chat_history） */
export async function recordChat(sessionId: string, role: 'user' | 'agent', content: string): Promise<void> {
  await api.post('/history/chat', { session_id: sessionId, role, content });
}
import api from './axios';
import type { RecommendResponse } from '../types/recommend';

/** 获取"猜你喜欢"推荐导师列表 */
export async function getRecommendations(): Promise<RecommendResponse> {
  const { data } = await api.get<RecommendResponse>('/recommend');
  return data;
}

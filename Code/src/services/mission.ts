import api from './axios';
import type { RuntimeEvent } from '../types/search';
import type { ReviewDecision, EvidenceRecord, MatchResult, TaskPlan } from '../stores/missionStore';

/** Mission 元信息（GET /api/mission） */
export interface MissionItem {
  id: number;
  trace_id: string;
  query: string;
  status: string;
  goal: string;
  advisor_ids: string[];
  source: string;
  created_at: string;
  updated_at: string;
}

/** GET /api/mission 列表响应 */
export interface MissionListResponse {
  items: MissionItem[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

/** GET /api/mission/:id/replay 响应 */
export interface MissionReplayResponse {
  mission: MissionItem;
  events: (RuntimeEvent & { seq?: number })[];
}

/** GET /api/mission — 列出当前用户的检索 Mission（分页，时间倒序） */
export async function listMissions(page = 1, pageSize = 20): Promise<MissionListResponse> {
  const { data } = await api.get<MissionListResponse>('/mission', { params: { page, pageSize } });
  return data;
}

/** GET /api/mission/:id/replay — 回放某次检索的完整事件序列 */
export async function replayMission(id: number): Promise<MissionReplayResponse> {
  const { data } = await api.get<MissionReplayResponse>(`/mission/${id}/replay`);
  return data;
}

/** DELETE /api/mission/:id — 删除单个 Mission */
export async function deleteMission(id: number): Promise<void> {
  await api.delete(`/mission/${id}`);
}

/** 导出 missionStore 的结构化类型供复用 */
export type { ReviewDecision, EvidenceRecord, MatchResult, TaskPlan };

import api from './axios';
import type { AdvisorDetail, AdvisorExplanation } from '../types/advisor';

/** 获取导师详情 */
export async function getAdvisorDetail(id: string): Promise<AdvisorDetail> {
  const { data } = await api.get<AdvisorDetail>(`/advisors/${encodeURIComponent(id)}`);
  return data;
}

/** 获取导师推理链 */
export async function getAdvisorExplanation(id: string): Promise<string> {
  const { data } = await api.get<AdvisorExplanation>(`/advisors/${encodeURIComponent(id)}/explanation`);
  return data.explanation;
}

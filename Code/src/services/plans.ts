import api from './axios';

export type PlanStatus = 'todo' | 'doing' | 'done' | 'cancelled';
export type PlanPriority = 'low' | 'medium' | 'high';

export interface ResearchPlan {
  id: number;
  title: string;
  description: string;
  status: PlanStatus;
  priority: PlanPriority;
  start_at?: string | null;
  due_at?: string | null;
  estimated_minutes: number;
  actual_minutes: number;
  reminder_at?: string | null;
  email_reminder: number;
  source: string;
  created_at: string;
  updated_at: string;
}

export type PlanInput = Omit<ResearchPlan, 'id' | 'source' | 'created_at' | 'updated_at'>;

export interface PlanSuggestion {
  kind: string;
  text: string;
  plan_id?: number;
}

export async function listPlans(): Promise<ResearchPlan[]> {
  return (await api.get('/plans')).data;
}

export async function createPlan(input: PlanInput): Promise<ResearchPlan> {
  return (await api.post('/plans', input)).data;
}

export async function updatePlan(id: number, input: PlanInput): Promise<ResearchPlan> {
  return (await api.put(`/plans/${id}`, input)).data;
}

export async function deletePlan(id: number): Promise<void> {
  await api.delete(`/plans/${id}`);
}

export async function getPlanSuggestions(): Promise<{ suggestions: PlanSuggestion[]; evidence_refs?: string[] }> {
  // plan_coach uses the shared AgentRun path; allow its configured 150s
  // budget plus network overhead before falling back to local suggestions.
  return (await api.post('/plans/suggest', {}, { timeout: 180000 })).data;
}

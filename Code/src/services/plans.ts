import api from './axios';

export type PlanStatus = 'todo' | 'doing' | 'done' | 'cancelled';
export type PlanPriority = 'low' | 'medium' | 'high';

export interface ResearchPlan {
  id: number;
  parent_plan_id?: number | null;
  title: string;
  description: string;
  deliverable?: string;
  acceptance_criteria?: string[];
  sequence?: number | null;
  status: PlanStatus;
  priority: PlanPriority;
  start_at?: string | null;
  due_at?: string | null;
  estimated_minutes: number;
  actual_minutes: number;
  execution_notes?: string;
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

export interface PlanDraft {
  title: string;
  description: string;
  deliverable?: string;
  acceptance_criteria?: string[];
  priority: PlanPriority;
  start_at?: string | null;
  due_at?: string | null;
  estimated_minutes: number;
  actual_minutes?: number;
  reminder_at?: string | null;
  email_reminder?: number;
  source_plan_id?: number | null;
  sequence?: number | null;
}

export interface PlanCoachResult {
  planning_summary?: string;
  capacity_assessment?: string;
  personalization_basis?: string[];
  milestones?: PlanDraft[];
  plan_drafts?: PlanDraft[];
  suggestions: PlanSuggestion[];
  risks?: string[];
  evidence_refs?: string[];
  generation?: { agent?: string; status?: string; reason?: string; model?: string };
}

export interface PlanReminder {
  id: number;
  title: string;
  status: PlanStatus;
  due_at?: string | null;
  reminder_at: string;
  email_reminder: number;
  parent_plan_id?: number | null;
  state: 'due' | 'upcoming';
}

export interface PlanCoachEvent { sequence?: number; payload?: { stage?: string; progress?: number; message?: string }; created_at?: string; }
export interface PlanCoachJob { run_id: string | null; status: string; artifact: PlanCoachResult | null; audit?: Record<string, unknown>; error?: string | null; events?: PlanCoachEvent[]; }

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

export async function completePlan(id: number, input: { execution_notes: string; actual_minutes: number }): Promise<ResearchPlan> {
  return (await api.post(`/plans/${id}/complete`, input)).data;
}

export async function getPlanSuggestions(): Promise<PlanCoachJob> {
  return (await api.post('/plans/suggest', {}, { timeout: 20000 })).data;
}

export async function getPlanSuggestionJob(runId: string): Promise<PlanCoachJob> {
  return (await api.get(`/plans/suggest/${runId}`, { timeout: 15000 })).data;
}

export async function getPlanSuggestionEvents(runId: string, afterSequence?: number): Promise<PlanCoachEvent[]> {
  const query = afterSequence ? `?after_sequence=${afterSequence}` : '';
  return (await api.get(`/plans/suggest/${runId}/events${query}`, { timeout: 15000 })).data.events || [];
}

export async function cancelPlanSuggestion(runId: string): Promise<PlanCoachJob> {
  return (await api.post(`/plans/suggest/${runId}/cancel`, {}, { timeout: 15000 })).data;
}

export async function applyPlanDrafts(plan_drafts: PlanDraft[]): Promise<ResearchPlan[]> {
  return (await api.post('/plans/suggest/apply', { plan_drafts })).data.created;
}

export async function getPlanReminders(): Promise<PlanReminder[]> {
  return (await api.get('/plans/reminders')).data;
}

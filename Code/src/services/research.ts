import api from './axios';

export type ResearchProjectStatus = 'idea' | 'literature_review' | 'design' | 'experiment' | 'analysis' | 'writing' | 'completed' | 'archived';

export interface ResearchProject {
  id: number;
  name: string;
  description: string;
  status: ResearchProjectStatus | string;
  goal: string;
  conversation_count?: number;
  conversations?: Array<{ id: number; title: string; surface: string; status: string; updated_at: string }>;
  created_at: string;
  updated_at: string;
}

export async function listProjects(): Promise<ResearchProject[]> {
  return (await api.get('/research/projects')).data;
}

export async function createProject(input: { name: string; description?: string; goal?: string }): Promise<ResearchProject> {
  return (await api.post('/research/projects', input)).data;
}

export async function updateProject(id: number, input: Partial<Pick<ResearchProject, 'name' | 'description' | 'goal' | 'status'>>): Promise<ResearchProject> {
  return (await api.patch(`/research/projects/${id}`, input)).data;
}


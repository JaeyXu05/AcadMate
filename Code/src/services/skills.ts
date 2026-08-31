import api from './axios';

export interface CustomSkill {
  id: number;
  name: string;
  description: string;
  prompt_template: string;
  trigger_mode: 'manual' | 'manual_or_suggest' | string;
  allowed_tools: string[];
  permissions: string[];
  status: 'draft' | 'enabled' | 'disabled' | string;
  version: number;
  created_at: string;
  updated_at: string;
}

export async function listSkills(): Promise<CustomSkill[]> { return (await api.get('/skills')).data; }
export async function createSkill(input: Partial<CustomSkill>): Promise<CustomSkill> { return (await api.post('/skills', input)).data; }
export async function updateSkill(id: number, input: Partial<CustomSkill>): Promise<CustomSkill> { return (await api.patch(`/skills/${id}`, input)).data; }
export async function validateSkill(id: number): Promise<{ valid: boolean; errors: string[]; note?: string }> { return (await api.post(`/skills/${id}/validate`)).data; }
export async function setSkillStatus(id: number, status: 'enabled' | 'disabled'): Promise<CustomSkill> { return (await api.post(`/skills/${id}/${status === 'enabled' ? 'enable' : 'disable'}`)).data; }


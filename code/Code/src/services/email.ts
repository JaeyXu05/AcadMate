import api from './axios';
import type { EmailDraft } from '../types/email';

/** 生成联系导师的邮件草稿 */
export async function generateEmail(advisorId: string): Promise<EmailDraft> {
  const { data } = await api.post<EmailDraft>('/email/generate', { advisor_id: advisorId });
  return data;
}

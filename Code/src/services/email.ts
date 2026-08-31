import api from './axios';
import type { EmailDraft } from '../types/email';

/** 生成联系导师的邮件草稿 */
export async function generateEmail(advisorId: string): Promise<EmailDraft> {
  const { data } = await api.post<EmailDraft>('/email/generate', { advisor_id: advisorId });
  return data;
}

export async function sendEmail(advisorId: string, subject: string, body: string) {
  return (await api.post('/email/send', { advisor_id: advisorId, subject, body }, { timeout: 60000 })).data;
}

export async function getEmailOutbox() {
  return (await api.get('/email/outbox')).data as { smtp_configured: boolean; items: Array<Record<string, any>> };
}

export async function getEmailInbox() {
  return (await api.get('/email/inbox', { timeout: 60000 })).data as {
    imap_configured: boolean;
    items: Array<{ uid: number; from: string; subject: string; date?: string; text: string }>;
  };
}

export async function getEmailStatus() {
  return (await api.get('/email/status', { timeout: 15000 })).data as {
    smtp: { configured: boolean; reachable: boolean | null; message: string };
    imap: { configured: boolean; reachable: boolean | null; message: string };
  };
}

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

export interface EmailSettings {
  smtp_host: string;
  smtp_port: number;
  smtp_secure: boolean;
  smtp_user: string;
  smtp_from: string;
  smtp_password_saved: boolean;
  /** 已保存密码回填值；仅在服务端确认该用户已保存密码时返回。 */
  smtp_password_value: string;
  remember_smtp_password: boolean;
  imap_host: string;
  imap_port: number;
  imap_secure: boolean;
  imap_user: string;
  imap_mailbox: string;
  imap_password_saved: boolean;
  /** IMAP 独立已保存密码回填值；未保存或与 SMTP 一致时按后端返回。 */
  imap_password_value: string;
  remember_imap_password: boolean;
  imap_same_as_smtp: boolean;
}

export async function sendEmailWithRecipients(
  advisorId: string,
  recipients: string[],
  subject: string,
  body: string,
  smtpPassword?: string,
) {
  return (await api.post('/email/send', {
    advisor_id: advisorId,
    recipients,
    subject,
    body,
    ...(smtpPassword ? { smtp_password: smtpPassword } : {}),
  }, { timeout: 60000 })).data;
}

export async function getEmailSettings() {
  return (await api.get('/email/settings')).data as EmailSettings;
}

export async function saveEmailSettings(payload: Partial<EmailSettings> & {
  smtp_password?: string;
  imap_password?: string;
}) {
  return (await api.put('/email/settings', payload)).data as EmailSettings;
}

export async function getEmailOutbox() {
  return (await api.get('/email/outbox')).data as { smtp_configured: boolean; items: Array<Record<string, any>> };
}

export async function getEmailInbox(imapPassword?: string) {
  return (await api.get('/email/inbox', {
    timeout: 60000,
    headers: imapPassword ? { 'X-IMAP-Password': imapPassword } : undefined,
  })).data as {
    imap_configured: boolean;
    items: Array<{ uid: number; from: string; subject: string; date?: string; text: string }>;
  };
}

export async function getEmailStatus(smtpPassword?: string, imapPassword?: string) {
  return (await api.get('/email/status', {
    timeout: 15000,
    headers: smtpPassword || imapPassword ? {
      ...(smtpPassword ? { 'X-SMTP-Password': smtpPassword } : {}),
      ...(imapPassword ? { 'X-IMAP-Password': imapPassword } : {}),
    } : undefined,
  })).data as {
    smtp: { configured: boolean; reachable: boolean | null; message: string };
    imap: { configured: boolean; reachable: boolean | null; message: string };
  };
}

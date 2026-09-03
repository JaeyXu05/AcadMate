import api from './axios';
import type { EmailDraft } from '../types/email';

export const EMAIL_SCENARIO_OPTIONS = [
  { value: 'postgraduate', label: '保研/考研联系导师' },
  { value: 'strong_research', label: '有科研/竞赛经历' },
  { value: 'strong_gpa', label: '成绩好但无科研经历' },
  { value: 'paper_reader', label: '认真读过老师论文' },
  { value: 'summer', label: '暑期/短期进组' },
  { value: 'thesis', label: '本科毕业设计进组' },
  { value: 'cross_major', label: '跨专业/转方向' },
  { value: 'limited_info', label: '主页信息有限' },
];

/** 生成联系导师的邮件草稿 */
export async function generateEmail(advisorId: string, scenario?: string): Promise<EmailDraft> {
  const { data } = await api.post<EmailDraft>('/email/generate', { advisor_id: advisorId, email_scenario: scenario });
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

export interface EmailAttachment {
  filename: string;
  contentBase64: string;
  contentType?: string;
  size: number;
}

export async function sendEmailWithRecipients(
  advisorId: string,
  recipients: string[],
  subject: string,
  body: string,
  smtpPassword?: string,
  attachments?: EmailAttachment[],
) {
  return (await api.post('/email/send', {
    advisor_id: advisorId,
    recipients,
    subject,
    body,
    ...(smtpPassword ? { smtp_password: smtpPassword } : {}),
    ...(attachments?.length ? {
      attachments: attachments.map(({ filename, contentBase64, contentType }) => ({ filename, contentBase64, contentType })),
    } : {}),
  }, { timeout: 180000 })).data;
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

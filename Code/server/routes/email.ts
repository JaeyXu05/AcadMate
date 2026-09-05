import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, type RagMentor } from '../data/ragAdvisors';
import { loadRecommendMemory, verifiedPaperTitles } from '../data/userMemory';
import { loadUserProfile } from '../data/growthStore';
import { buildScenarioEmail, EMAIL_SCENARIOS, type EmailScenarioId } from '../data/emailTemplates';
import {
  drainEmailOutbox, getEmailSettings, imapConfigured, probeImap, probeSmtp,
  queueEmail, readInbox, saveEmailSettings, smtpConfigured,
  type EmailAttachmentInput,
} from '../services/mailer';
import { ensureProductivitySchema, getDb } from '../db';

export const emailRouter = Router();

emailRouter.use(authMiddleware);

interface EmailRequestBody {
  advisor_id?: string;
  subject?: string;
  body?: string;
  recipients?: unknown;
  smtp_password?: unknown;
  attachments?: unknown;
  email_scenario?: unknown;
}

const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig;
const USTC_CLIENT_PASSWORD_PATTERN = /^[A-Za-z0-9]{16}$/;
const MAX_EMAIL_ATTACHMENTS = 5;
const MAX_EMAIL_ATTACHMENT_BYTES = 20 * 1024 * 1024;

function validatedEmailAttachments(value: unknown): { ok: true; items: EmailAttachmentInput[] } | { ok: false; error: string } {
  if (value === undefined || value === null) return { ok: true, items: [] };
  if (!Array.isArray(value)) return { ok: false, error: '附件格式不正确' };
  if (value.length > MAX_EMAIL_ATTACHMENTS) return { ok: false, error: `一次最多添加 ${MAX_EMAIL_ATTACHMENTS} 个附件` };
  const items: EmailAttachmentInput[] = [];
  let totalBytes = 0;
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') return { ok: false, error: '附件格式不正确' };
    const item = raw as Record<string, unknown>;
    const filename = String(item.filename || '').trim().slice(0, 180);
    const content = String(item.contentBase64 || '');
    const dataStart = content.indexOf(',');
    const base64 = dataStart >= 0 ? content.slice(dataStart + 1) : content;
    if (!filename || !base64 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64.replace(/\s+/g, ''))) {
      return { ok: false, error: '附件内容无效，请重新选择文件' };
    }
    totalBytes += Math.floor((base64.replace(/\s+/g, '').length * 3) / 4);
    if (totalBytes > MAX_EMAIL_ATTACHMENT_BYTES) {
      return { ok: false, error: '附件总大小不能超过 20MB' };
    }
    items.push({
      filename,
      contentBase64: base64.replace(/\s+/g, ''),
      contentType: typeof item.contentType === 'string' && item.contentType.trim() ? item.contentType.trim().slice(0, 100) : undefined,
    });
  }
  return { ok: true, items };
}

function isUstcMailHost(value: unknown): boolean {
  return String(value || '').toLowerCase().includes('ustc.edu.cn');
}

function isUstcClientPassword(value: unknown): boolean {
  return USTC_CLIENT_PASSWORD_PATTERN.test(String(value || '').trim());
}

function mentorEmail(candidate: RagMentor): string {
  const sources = [
    candidate.source_metadata?.profile_email,
    ...(String(candidate.source_metadata?.profile_bio || '').match(EMAIL_PATTERN) || []),
    ...(String(candidate.recruitment_status || '').match(EMAIL_PATTERN) || []),
  ];
  for (const source of sources) {
    const address = String(source || '').trim().toLowerCase();
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) return address;
  }
  return '';
}

function normalizeRecipients(value: unknown, fallback = ''): string[] {
  const raw = Array.isArray(value) ? value : [value || fallback];
  const addresses = raw
    .flatMap((item) => String(item || '').split(/[;,，；\s]+/))
    .map((item) => item.trim().toLowerCase())
    .filter((item, index, all) => item && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(item) && all.indexOf(item) === index);
  return addresses.slice(0, 20);
}

emailRouter.get('/settings', (req: AuthRequest, res: Response) => {
  res.json(getEmailSettings(req.userId!));
});

emailRouter.put('/settings', (req: AuthRequest, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const addressFields = ['smtp_user', 'smtp_from', 'imap_user'];
  for (const field of addressFields) {
    const value = String(body[field] || '').trim();
    const address = value.match(/<\s*([^<>\s]+@[^<>\s]+)\s*>/)?.[1] || value;
    if (value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      res.status(400).json({ message: `${field} 不是有效邮箱地址` });
      return;
    }
  }
  const portFields = ['smtp_port', 'imap_port'];
  for (const field of portFields) {
    const port = Number(body[field]);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      res.status(400).json({ message: `${field} 不是有效端口` });
      return;
    }
  }
  const hostFields = ['smtp_host', 'imap_host'];
  for (const field of hostFields) {
    const value = String(body[field] || '').trim();
    if (value && (value.includes('@') || /\s/.test(value))) {
      res.status(400).json({ message: `${field} 应填写服务器地址，例如 mail.ustc.edu.cn，不是邮箱地址` });
      return;
    }
  }
  const smtpPasswordValue = body.smtp_password === undefined ? '' : String(body.smtp_password || '');
  const currentSettings = getEmailSettings(req.userId!);
  const effectiveSmtpHost = String(body.smtp_host ?? currentSettings.smtp_host);
  if (smtpPasswordValue && isUstcMailHost(effectiveSmtpHost) && !isUstcClientPassword(smtpPasswordValue)) {
    res.status(400).json({ message: 'USTC 客户端专用密码应为 16 位字母或数字（不含空格），请去掉空格后重试' });
    return;
  }
  res.json(saveEmailSettings(req.userId!, body));
});

emailRouter.get('/status', async (req: AuthRequest, res: Response) => {
  const smtpPassword = req.get('x-smtp-password') || undefined;
  const imapPassword = req.get('x-imap-password') || smtpPassword;
  const [smtp, imap] = await Promise.all([
    probeSmtp(4000, req.userId!, smtpPassword),
    probeImap(4000, req.userId!, imapPassword),
  ]);
  res.json({ smtp, imap });
});

emailRouter.post('/generate', (req: AuthRequest, res: Response) => {
  const { advisor_id, email_scenario } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id) {
    res.status(400).json({ message: '请提供 advisor_id' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  if (!candidate) {
    res.status(404).json({ message: '未找到该导师' });
    return;
  }
  const profile = loadUserProfile(req.userId!);
  const papers = verifiedPaperTitles(req.userId!, advisor_id);
  const memory = loadRecommendMemory(req.userId!);
  const requestedScenario = String(email_scenario || 'postgraduate') as EmailScenarioId;
  const scenario = EMAIL_SCENARIOS.some((item) => item.value === requestedScenario)
    ? requestedScenario
    : 'postgraduate';
  const scenarioDraft = buildScenarioEmail(scenario, {
    candidate,
    profile,
    papers,
    memoryCore: memory.core,
  });
  res.json({
    ...scenarioDraft,
    default_recipients: mentorEmail(candidate) ? [mentorEmail(candidate)] : [],
    source: `local:${scenario}`,
  });
});

emailRouter.post('/send', async (req: AuthRequest, res: Response) => {
  const { advisor_id, subject, body, recipients, smtp_password, attachments } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id || !String(subject || '').trim() || !String(body || '').trim()) {
    res.status(400).json({ message: '导师、主题和正文不能为空' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  if (!candidate) { res.status(404).json({ message: '未找到该导师' }); return; }
  const targetRecipients = normalizeRecipients(recipients, mentorEmail(candidate));
  if (!targetRecipients.length) {
    res.status(400).json({ message: '请至少填写一个有效收件人邮箱' });
    return;
  }
  const validatedAttachments = validatedEmailAttachments(attachments);
  if (!validatedAttachments.ok) {
    res.status(400).json({ message: validatedAttachments.error });
    return;
  }
  ensureProductivitySchema(getDb());
  const outboxIds = targetRecipients.map((recipient) => queueEmail({
    userId: req.userId!, recipient,
    subject: String(subject).replace(/[\r\n]+/g, ' ').trim().slice(0, 300),
    body: String(body).trim().slice(0, 30000), kind: `advisor-contact:${advisor_id}`,
    attachments: validatedAttachments.items,
  }));
  const transientPassword = typeof smtp_password === 'string' ? smtp_password : undefined;
  const delivery = await drainEmailOutbox(targetRecipients.length, req.userId!, transientPassword, outboxIds);
  const placeholders = outboxIds.map((id) => getDb().prepare('SELECT id,recipient,subject,kind,status,sent_at,error,created_at FROM email_outbox WHERE id=? AND user_id=?').get(id, req.userId!));
  const rows = placeholders.filter(Boolean) as Array<{ status?: string }>;
  const allSent = rows.length === outboxIds.length && rows.every((row) => row.status === 'sent');
  res.status(allSent ? 200 : 202).json({ item: rows[0], items: rows, smtp_configured: delivery.configured });
});

emailRouter.get('/outbox', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const items = getDb().prepare(
    'SELECT id,recipient,subject,kind,status,scheduled_at,sent_at,error,created_at FROM email_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100',
  ).all(req.userId!);
  res.json({ smtp_configured: smtpConfigured(req.userId!), items });
});

emailRouter.get('/inbox', async (req: AuthRequest, res: Response) => {
  const password = req.get('x-imap-password') || req.get('x-smtp-password') || undefined;
  if (!imapConfigured(req.userId!, password)) { res.json({ imap_configured: false, items: [] }); return; }
  try {
    res.json({ imap_configured: true, items: await readInbox(30, req.userId!, password) });
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? `读取收件箱失败：${error.message}` : '读取收件箱失败' });
  }
});

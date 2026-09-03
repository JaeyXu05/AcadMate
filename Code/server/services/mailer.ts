import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'crypto';
import nodemailer from 'nodemailer';
import { ImapFlow } from 'imapflow';
import { simpleParser } from 'mailparser';
import { getDb } from '../db';

const PLACEHOLDER_VALUES = new Set([
  '',
  'account@example.com',
  'smtp.example.com',
  'imap.example.com',
  'replace-with-an-app-password',
  'replace-with-a-long-random-secret',
  'changeme',
  'change-me',
]);
// 默认面向中国科大邮箱；用户保存自己的主机值后，以后端 DB 中已保存值为准。
const DEFAULT_MAIL_HOST = 'mail.ustc.edu.cn';

function configuredValue(value: unknown): string {
  const text = String(value ?? '').trim();
  const lowered = text.toLowerCase();
  return PLACEHOLDER_VALUES.has(lowered) || lowered.includes('account@example.com') ? '' : text;
}

function isUstcMailHost(value: unknown): boolean {
  return String(value || '').toLowerCase().includes('ustc.edu.cn');
}

function normalizeMailHostPassword(host: string, password: string): string {
  return isUstcMailHost(host) ? password.replace(/\s+/g, '') : password;
}

function validAddress(value: unknown): boolean {
  const text = configuredValue(value);
  const displayAddress = text.match(/<\s*([^<>\s]+@[^<>\s]+)\s*>/)?.[1] || text;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(displayAddress);
}

export interface OutboxMessage {
  userId: number;
  recipient: string;
  subject: string;
  body: string;
  kind: string;
  scheduledAt?: string | null;
  attachments?: EmailAttachmentInput[];
}

export interface EmailAttachmentInput {
  filename: string;
  contentBase64: string;
  contentType?: string;
}

interface StoredEmailAccount {
  user_id: number;
  smtp_host: string;
  smtp_port: number;
  smtp_secure: number;
  smtp_user: string;
  smtp_from: string;
  smtp_pass_encrypted: string;
  smtp_remember: number;
  imap_host: string;
  imap_port: number;
  imap_secure: number;
  imap_user: string;
  imap_mailbox: string;
  imap_pass_encrypted: string;
  imap_remember: number;
  imap_same_as_smtp: number;
}

interface EffectiveMailAccount {
  smtpHost: string;
  smtpPort: number;
  smtpSecure: boolean;
  smtpUser: string;
  smtpFrom: string;
  smtpPass: string;
  imapHost: string;
  imapPort: number;
  imapSecure: boolean;
  imapUser: string;
  imapMailbox: string;
  imapPass: string;
}

export interface EmailSettingsInput {
  smtp_host?: unknown;
  smtp_port?: unknown;
  smtp_secure?: unknown;
  smtp_user?: unknown;
  smtp_from?: unknown;
  smtp_password?: unknown;
  remember_smtp_password?: unknown;
  imap_host?: unknown;
  imap_port?: unknown;
  imap_secure?: unknown;
  imap_user?: unknown;
  imap_mailbox?: unknown;
  imap_password?: unknown;
  remember_imap_password?: unknown;
  imap_same_as_smtp?: unknown;
}

export interface EmailSettingsView {
  smtp_host: string;
  smtp_port: number;
  smtp_secure: boolean;
  smtp_user: string;
  smtp_from: string;
  smtp_password_saved: boolean;
  /** 仅回给已登录用户本人用于回填/查看；无已保存密码时为空字符串。 */
  smtp_password_value: string;
  remember_smtp_password: boolean;
  imap_host: string;
  imap_port: number;
  imap_secure: boolean;
  imap_user: string;
  imap_mailbox: string;
  imap_password_saved: boolean;
  /** IMAP 未与 SMTP 一致且已有独立密码时回填；无则空字符串。 */
  imap_password_value: string;
  remember_imap_password: boolean;
  imap_same_as_smtp: boolean;
}

function credentialKey(): Buffer {
  // 优先使用独立密钥；本地启动器已经持久化 JWT_SECRET，因此可作为兼容回退。
  const secret = configuredValue(process.env.MAIL_CREDENTIAL_KEY)
    || configuredValue(process.env.JWT_SECRET)
    || 'local-email-credential-key';
  return createHash('sha256').update(secret).digest();
}

function encryptPassword(password: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', credentialKey(), iv);
  const encrypted = Buffer.concat([cipher.update(password, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${iv.toString('base64')}.${tag.toString('base64')}.${encrypted.toString('base64')}`;
}

function decryptPassword(value: unknown): string {
  try {
    const [ivText, tagText, encryptedText] = String(value || '').split('.');
    if (!ivText || !tagText || !encryptedText) return '';
    const decipher = createDecipheriv('aes-256-gcm', credentialKey(), Buffer.from(ivText, 'base64'));
    decipher.setAuthTag(Buffer.from(tagText, 'base64'));
    return Buffer.concat([
      decipher.update(Buffer.from(encryptedText, 'base64')),
      decipher.final(),
    ]).toString('utf8');
  } catch {
    return '';
  }
}

function storedAccount(userId?: number): StoredEmailAccount | undefined {
  if (!userId) return undefined;
  return getDb().prepare('SELECT * FROM email_accounts WHERE user_id=?').get(userId) as StoredEmailAccount | undefined;
}

function textOr(value: unknown, fallback: string): string {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function portOr(value: unknown, fallback: number): number {
  const port = Number(value);
  return Number.isInteger(port) && port > 0 && port <= 65535 ? port : fallback;
}

function effectiveAccount(userId?: number, transientSmtpPassword?: string, transientImapPassword?: string): EffectiveMailAccount {
  const row = storedAccount(userId);
  const smtpHost = textOr(row?.smtp_host, configuredValue(process.env.SMTP_HOST) || DEFAULT_MAIL_HOST);
  const smtpEnvConfigured = Boolean(configuredValue(process.env.SMTP_HOST));
  const smtpPort = portOr(row?.smtp_port, smtpEnvConfigured ? Number(process.env.SMTP_PORT || 465) : 465);
  const smtpSecure = row ? Boolean(row.smtp_secure) : (smtpEnvConfigured ? String(process.env.SMTP_SECURE || 'true').toLowerCase() !== 'false' : true);
  const smtpUser = textOr(row?.smtp_user, configuredValue(process.env.SMTP_USER));
  const smtpFrom = textOr(row?.smtp_from, configuredValue(process.env.SMTP_FROM));
  const smtpPass = normalizeMailHostPassword(
    smtpHost,
    transientSmtpPassword || decryptPassword(row?.smtp_pass_encrypted) || configuredValue(process.env.SMTP_PASS),
  );
  const sameCredentials = Boolean(row?.imap_same_as_smtp);
  const imapHost = sameCredentials ? smtpHost : textOr(row?.imap_host, configuredValue(process.env.IMAP_HOST) || DEFAULT_MAIL_HOST);
  return {
    smtpHost,
    smtpPort,
    smtpSecure,
    smtpUser,
    smtpFrom,
    smtpPass,
    imapHost,
    imapPort: portOr(row?.imap_port, Number(process.env.IMAP_PORT || 993)),
    imapSecure: sameCredentials ? true : (row ? Boolean(row.imap_secure) : String(process.env.IMAP_SECURE || 'true').toLowerCase() !== 'false'),
    imapUser: sameCredentials ? smtpUser : textOr(row?.imap_user, configuredValue(process.env.IMAP_USER)),
    imapMailbox: textOr(row?.imap_mailbox, String(process.env.IMAP_MAILBOX || 'INBOX')),
    imapPass: sameCredentials
      ? normalizeMailHostPassword(smtpHost, transientSmtpPassword || smtpPass)
      : normalizeMailHostPassword(
        imapHost,
        transientImapPassword || decryptPassword(row?.imap_pass_encrypted) || configuredValue(process.env.IMAP_PASS),
      ),
  };
}

function smtpAccountConfigured(account: EffectiveMailAccount): boolean {
  return Boolean(account.smtpHost && validAddress(account.smtpUser) && account.smtpPass
    && validAddress(account.smtpFrom || account.smtpUser));
}

function imapAccountConfigured(account: EffectiveMailAccount): boolean {
  return Boolean(account.imapHost && validAddress(account.imapUser) && account.imapPass);
}

export function smtpConfigured(userId?: number, transientPassword?: string): boolean {
  return smtpAccountConfigured(effectiveAccount(userId, transientPassword));
}

export function imapConfigured(userId?: number, transientPassword?: string): boolean {
  return imapAccountConfigured(effectiveAccount(userId, undefined, transientPassword));
}

export function getEmailSettings(userId: number): EmailSettingsView {
  const row = storedAccount(userId);
  const account = effectiveAccount(userId);
  const sameCredentials = Boolean(row?.imap_same_as_smtp);
  const smtpPasswordValue = row?.smtp_pass_encrypted
    ? normalizeMailHostPassword(account.smtpHost, decryptPassword(row.smtp_pass_encrypted))
    : '';
  const imapPasswordValue = sameCredentials
    ? smtpPasswordValue
    : (row?.imap_pass_encrypted ? normalizeMailHostPassword(account.imapHost, decryptPassword(row.imap_pass_encrypted)) : '');
  return {
    smtp_host: account.smtpHost,
    smtp_port: account.smtpPort,
    smtp_secure: account.smtpSecure,
    smtp_user: account.smtpUser,
    smtp_from: account.smtpFrom || account.smtpUser,
    smtp_password_saved: Boolean(row?.smtp_pass_encrypted),
    smtp_password_value: smtpPasswordValue,
    remember_smtp_password: Boolean(row?.smtp_remember && row.smtp_pass_encrypted),
    imap_host: account.imapHost,
    imap_port: account.imapPort,
    imap_secure: account.imapSecure,
    imap_user: account.imapUser,
    imap_mailbox: account.imapMailbox,
    imap_password_saved: Boolean(row?.imap_pass_encrypted || (sameCredentials && row?.smtp_pass_encrypted)),
    imap_password_value: imapPasswordValue,
    remember_imap_password: Boolean((row?.imap_remember && row.imap_pass_encrypted) || (sameCredentials && row?.smtp_remember && row.smtp_pass_encrypted)),
    imap_same_as_smtp: sameCredentials,
  };
}

export function saveEmailSettings(userId: number, input: EmailSettingsInput): EmailSettingsView {
  const db = getDb();
  const previous = storedAccount(userId);
  const stringField = (value: unknown, fallback: string): string => value === undefined ? fallback : String(value || '').trim();
  const smtpPassword = input.smtp_password === undefined ? '' : String(input.smtp_password || '');
  const imapPassword = input.imap_password === undefined ? '' : String(input.imap_password || '');
  // 用户输入新密码并点击保存时，必须更新对应协议的凭据；
  // 复选框仍用于控制已有密码是否继续保留。
  const rememberSmtp = Boolean(input.remember_smtp_password) || Boolean(smtpPassword);
  const rememberImap = Boolean(input.remember_imap_password) || Boolean(imapPassword);
  const sameCredentials = input.imap_same_as_smtp === undefined
    ? Boolean(previous?.imap_same_as_smtp)
    : Boolean(input.imap_same_as_smtp);
  const defaultSmtpSecure = configuredValue(process.env.SMTP_HOST)
    ? String(process.env.SMTP_SECURE || 'true').toLowerCase() === 'true'
    : true;
  const smtpHost = stringField(input.smtp_host, previous?.smtp_host || configuredValue(process.env.SMTP_HOST) || DEFAULT_MAIL_HOST);
  const smtpPort = portOr(input.smtp_port, previous?.smtp_port || (configuredValue(process.env.SMTP_HOST) ? Number(process.env.SMTP_PORT || 465) : 465));
  const smtpSecure = input.smtp_secure === undefined
    ? (previous?.smtp_secure ?? (defaultSmtpSecure ? 1 : 0))
    : (input.smtp_secure ? 1 : 0);
  const smtpUser = stringField(input.smtp_user, previous?.smtp_user || configuredValue(process.env.SMTP_USER));
  const smtpFrom = stringField(input.smtp_from, previous?.smtp_from || configuredValue(process.env.SMTP_FROM));
  const smtpEncrypted = rememberSmtp
    ? (smtpPassword ? encryptPassword(smtpPassword) : String(previous?.smtp_pass_encrypted || ''))
    : '';
  const imapEncrypted = sameCredentials
    ? smtpEncrypted
    : (rememberImap
      ? (imapPassword ? encryptPassword(imapPassword) : String(previous?.imap_pass_encrypted || ''))
      : '');
  const imapPort = portOr(input.imap_port, previous?.imap_port || Number(process.env.IMAP_PORT || 993));
  const imapMailbox = stringField(input.imap_mailbox, previous?.imap_mailbox || String(process.env.IMAP_MAILBOX || 'INBOX'));
  db.prepare(`
    INSERT INTO email_accounts
      (user_id, smtp_host, smtp_port, smtp_secure, smtp_user, smtp_from,
       smtp_pass_encrypted, smtp_remember, imap_host, imap_port, imap_secure,
       imap_user, imap_mailbox, imap_pass_encrypted, imap_remember, imap_same_as_smtp, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
    ON CONFLICT(user_id) DO UPDATE SET
      smtp_host=excluded.smtp_host, smtp_port=excluded.smtp_port,
      smtp_secure=excluded.smtp_secure, smtp_user=excluded.smtp_user,
      smtp_from=excluded.smtp_from, smtp_pass_encrypted=excluded.smtp_pass_encrypted,
      smtp_remember=excluded.smtp_remember, imap_host=excluded.imap_host,
      imap_port=excluded.imap_port, imap_secure=excluded.imap_secure,
      imap_user=excluded.imap_user, imap_mailbox=excluded.imap_mailbox,
      imap_pass_encrypted=excluded.imap_pass_encrypted,
      imap_remember=excluded.imap_remember, imap_same_as_smtp=excluded.imap_same_as_smtp,
      updated_at=excluded.updated_at
  `).run(
    userId,
    smtpHost,
    smtpPort,
    smtpSecure,
    smtpUser,
    smtpFrom,
    smtpEncrypted,
    smtpEncrypted ? 1 : 0,
    sameCredentials ? smtpHost : stringField(input.imap_host, previous?.imap_host || configuredValue(process.env.IMAP_HOST) || DEFAULT_MAIL_HOST),
    imapPort,
    sameCredentials ? 1 : (input.imap_secure === undefined ? (previous?.imap_secure ?? 1) : (input.imap_secure ? 1 : 0)),
    sameCredentials ? smtpUser : stringField(input.imap_user, previous?.imap_user || configuredValue(process.env.IMAP_USER)),
    imapMailbox,
    imapEncrypted,
    imapEncrypted ? 1 : 0,
    sameCredentials ? 1 : 0,
  );
  return getEmailSettings(userId);
}

export interface MailProbe {
  configured: boolean;
  reachable: boolean | null;
  message: string;
}

function mailProbeError(error: unknown, protocol: 'SMTP' | 'IMAP'): string {
  const detail = error instanceof Error ? error.message : String(error || '未知错误');
  if (protocol === 'SMTP' && /auth error limit exceed|IP.*rejected|too many authentication/i.test(detail)) {
    return '不通：邮箱服务器因多次认证失败暂时限制了 SMTP 登录，请等待解限后再试';
  }
  if (/535|authentication failed|invalid login/i.test(detail)) {
    return `不通：${protocol} 用户名或客户端专用密码错误`;
  }
  return `不通：${detail.slice(0, 120)}`;
}

export async function probeSmtp(timeoutMs = 4000, userId?: number, transientPassword?: string): Promise<MailProbe> {
  const account = effectiveAccount(userId, transientPassword);
  if (!smtpAccountConfigured(account)) {
    return { configured: false, reachable: null, message: '未配置真实 SMTP 主机、账号和应用密码' };
  }
  const transport = nodemailer.createTransport({
    host: account.smtpHost,
    port: account.smtpPort,
    secure: account.smtpSecure,
    auth: { user: account.smtpUser, pass: account.smtpPass },
    connectionTimeout: timeoutMs,
    socketTimeout: timeoutMs,
  });
  try {
    await transport.verify();
    return { configured: true, reachable: true, message: '通' };
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      message: mailProbeError(error, 'SMTP'),
    };
  } finally {
    transport.close();
  }
}

export async function probeImap(timeoutMs = 4000, userId?: number, transientPassword?: string): Promise<MailProbe> {
  const account = effectiveAccount(userId, transientPassword, transientPassword);
  if (!imapAccountConfigured(account)) {
    return { configured: false, reachable: null, message: '未配置真实 IMAP 主机、账号和应用密码' };
  }
  const client = new ImapFlow({
    host: account.imapHost,
    port: account.imapPort,
    secure: account.imapSecure,
    auth: { user: account.imapUser, pass: account.imapPass },
    logger: false,
  });
  // ImapFlow 连接超时后可能在 Promise 已 reject 之后再异步发出 error；
  // 注册监听器，避免一次失败的探测让整个 D 后端进程退出。
  client.on('error', () => undefined);
  const timer = setTimeout(() => { try { client.close(); } catch { /* timeout abort */ } }, timeoutMs);
  try {
    await client.connect();
    await client.logout().catch(() => undefined);
    return { configured: true, reachable: true, message: '通' };
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      message: mailProbeError(error, 'IMAP'),
    };
  } finally {
    clearTimeout(timer);
  }
}

export function configuredImapUser(userId?: number): string {
  return effectiveAccount(userId).imapUser.toLowerCase();
}

export function queueEmail(message: OutboxMessage): number {
  const result = getDb().prepare(
    `INSERT INTO email_outbox
      (user_id, recipient, subject, body, kind, status, scheduled_at, attachments_json)
     VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)`,
  ).run(
    message.userId,
    message.recipient,
    message.subject,
    message.body,
    message.kind,
    message.scheduledAt ?? null,
    JSON.stringify(message.attachments ?? []),
  );
  return Number(result.lastInsertRowid);
}

function parseEmailAttachments(value: unknown): EmailAttachmentInput[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is EmailAttachmentInput => Boolean(item) && typeof item === 'object')
    .map((item) => {
      const entry = item as Record<string, unknown>;
      return {
        filename: String(entry.filename || '附件').slice(0, 180),
        contentBase64: String(entry.contentBase64 || ''),
        contentType: typeof entry.contentType === 'string' && entry.contentType
          ? entry.contentType.slice(0, 100)
          : undefined,
      };
    })
    .filter((item) => item.filename && item.contentBase64);
}

export async function drainEmailOutbox(
  limit = 10,
  userId?: number,
  transientPassword?: string,
  messageIds?: number[],
): Promise<{ sent: number; failed: number; configured: boolean }> {
  const account = effectiveAccount(userId, transientPassword);
  if (!smtpAccountConfigured(account)) return { sent: 0, failed: 0, configured: false };
  const db = getDb();
  const userFilter = userId ? 'AND email_outbox.user_id=?' : '';
  const selectedIds = Array.isArray(messageIds) ? messageIds.filter((id) => Number.isInteger(id) && id > 0) : [];
  const idFilter = selectedIds.length ? `AND email_outbox.id IN (${selectedIds.map(() => '?').join(',')})` : '';
  const rows = db.prepare(
    `SELECT email_outbox.id, email_outbox.user_id, email_outbox.recipient, email_outbox.subject,
            email_outbox.body, email_outbox.attachments_json, users.email AS reply_to
       FROM email_outbox
       JOIN users ON users.id = email_outbox.user_id
      WHERE email_outbox.status IN ('queued', 'retry')
        AND email_outbox.attempt_count < 5
        AND (email_outbox.scheduled_at IS NULL OR datetime(email_outbox.scheduled_at) <= datetime('now','localtime'))
        ${userFilter}
        ${idFilter}
      ORDER BY email_outbox.id LIMIT ?`,
  ).all(...(userId ? [userId, ...selectedIds, limit] : [...selectedIds, limit])) as Array<{
    id: number;
    user_id: number;
    recipient: string;
    subject: string;
    body: string;
    attachments_json?: string | null;
    reply_to?: string;
  }>;
  if (!rows.length) return { sent: 0, failed: 0, configured: smtpAccountConfigured(account) };
  let sent = 0;
  let failed = 0;
  let configured = false;
  for (const row of rows) {
    const rowAccount = effectiveAccount(userId ?? row.user_id, userId === row.user_id ? transientPassword : undefined);
    if (!smtpAccountConfigured(rowAccount)) continue;
    configured = true;
    const parsedAttachments = parseEmailAttachments(row.attachments_json).map((attachment) => ({
      filename: attachment.filename,
      contentType: attachment.contentType,
      content: Buffer.from(attachment.contentBase64, 'base64'),
    }));
    const transport = nodemailer.createTransport({
      host: rowAccount.smtpHost,
      port: rowAccount.smtpPort,
      secure: rowAccount.smtpSecure,
      auth: { user: rowAccount.smtpUser, pass: rowAccount.smtpPass },
      connectionTimeout: 15_000,
      socketTimeout: 30_000,
    });
    try {
      await transport.sendMail({
        from: rowAccount.smtpFrom || rowAccount.smtpUser,
        to: row.recipient,
        replyTo: validAddress(row.reply_to) ? row.reply_to : undefined,
        subject: row.subject,
        text: row.body,
        ...(parsedAttachments.length ? { attachments: parsedAttachments } : {}),
      });
      db.prepare(
        `UPDATE email_outbox SET status='sent', sent_at=datetime('now','localtime'), error=NULL WHERE id=?`,
      ).run(row.id);
      sent += 1;
    } catch (error) {
      db.prepare(`UPDATE email_outbox SET
        attempt_count=attempt_count+1,
        last_attempt_at=datetime('now','localtime'),
        status=CASE WHEN attempt_count+1 >= 5 THEN 'failed' ELSE 'retry' END,
        error=? WHERE id=?`).run(
        error instanceof Error ? error.message.slice(0, 500) : String(error).slice(0, 500),
        row.id,
      );
      failed += 1;
    } finally {
      transport.close();
    }
  }
  return { sent, failed, configured };
}

export interface InboxMessage {
  uid: number;
  from: string;
  subject: string;
  date?: string;
  text: string;
}

export async function readInbox(limit = 30, userId?: number, transientPassword?: string): Promise<InboxMessage[]> {
  const account = effectiveAccount(userId, transientPassword, transientPassword);
  if (!imapAccountConfigured(account)) return [];
  const client = new ImapFlow({
    host: account.imapHost,
    port: account.imapPort,
    secure: account.imapSecure,
    auth: { user: account.imapUser, pass: account.imapPass },
    logger: false,
  });
  client.on('error', () => undefined);
  const timeoutMs = Math.max(2_000, Number(process.env.IMAP_READ_TIMEOUT_MS || 15_000));
  const timer = setTimeout(() => {
    try { void client.close(); } catch { /* timeout abort */ }
  }, timeoutMs);
  let lock: Awaited<ReturnType<typeof client.getMailboxLock>> | null = null;
  try {
    await client.connect();
    lock = await client.getMailboxLock(account.imapMailbox);
    const exists = Number(client.mailbox && client.mailbox.exists || 0);
    if (!exists) return [];
    const start = Math.max(1, exists - Math.max(1, Math.min(limit, 100)) + 1);
    const messages: InboxMessage[] = [];
    for await (const item of client.fetch(`${start}:*`, { uid: true, envelope: true, source: true })) {
      const parsed = item.source ? await simpleParser(item.source) : null;
      messages.push({
        uid: Number(item.uid),
        from: parsed?.from?.text || item.envelope?.from?.map((value) => value.address).filter(Boolean).join(', ') || '',
        subject: parsed?.subject || item.envelope?.subject || '(无主题)',
        date: (parsed?.date || item.envelope?.date)?.toISOString(),
        text: String(parsed?.text || '').trim().slice(0, 8000),
      });
    }
    return messages.sort((left, right) => right.uid - left.uid);
  } finally {
    clearTimeout(timer);
    lock?.release();
    await client.logout().catch(() => undefined);
  }
}

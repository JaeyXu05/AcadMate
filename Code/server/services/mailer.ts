import nodemailer from 'nodemailer';
import { ImapFlow } from 'imapflow';
import { simpleParser } from 'mailparser';
import { getDb } from '../db';

export interface OutboxMessage {
  userId: number;
  recipient: string;
  subject: string;
  body: string;
  kind: string;
  scheduledAt?: string | null;
}

export function smtpConfigured(): boolean {
  return Boolean(process.env.SMTP_HOST && process.env.SMTP_FROM);
}

export function imapConfigured(): boolean {
  return Boolean(process.env.IMAP_HOST && process.env.IMAP_USER && process.env.IMAP_PASS);
}

export interface MailProbe {
  configured: boolean;
  reachable: boolean | null;
  message: string;
}

export async function probeSmtp(timeoutMs = 4000): Promise<MailProbe> {
  if (!smtpConfigured()) {
    return { configured: false, reachable: null, message: '未配置' };
  }
  const transport = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE || '').toLowerCase() === 'true',
    auth: process.env.SMTP_USER
      ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS || '' }
      : undefined,
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
      message: error instanceof Error ? `不通：${error.message.slice(0, 120)}` : '不通',
    };
  } finally {
    transport.close();
  }
}

export async function probeImap(timeoutMs = 4000): Promise<MailProbe> {
  if (!imapConfigured()) {
    return { configured: false, reachable: null, message: '未配置' };
  }
  const client = new ImapFlow({
    host: String(process.env.IMAP_HOST),
    port: Number(process.env.IMAP_PORT || 993),
    secure: String(process.env.IMAP_SECURE || 'true').toLowerCase() !== 'false',
    auth: { user: String(process.env.IMAP_USER), pass: String(process.env.IMAP_PASS) },
    logger: false,
  });
  const timer = setTimeout(() => { try { client.close(); } catch { /* timeout abort */ } }, timeoutMs);
  try {
    await client.connect();
    await client.logout().catch(() => undefined);
    return { configured: true, reachable: true, message: '通' };
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      message: error instanceof Error ? `不通：${error.message.slice(0, 120)}` : '不通',
    };
  } finally {
    clearTimeout(timer);
  }
}

export function configuredImapUser(): string {
  return String(process.env.IMAP_USER || '').trim().toLowerCase();
}

export function queueEmail(message: OutboxMessage): number {
  const result = getDb().prepare(
    `INSERT INTO email_outbox
      (user_id, recipient, subject, body, kind, status, scheduled_at)
     VALUES (?, ?, ?, ?, ?, 'queued', ?)`,
  ).run(
    message.userId,
    message.recipient,
    message.subject,
    message.body,
    message.kind,
    message.scheduledAt ?? null,
  );
  return Number(result.lastInsertRowid);
}

export async function drainEmailOutbox(limit = 10): Promise<{ sent: number; failed: number; configured: boolean }> {
  if (!smtpConfigured()) return { sent: 0, failed: 0, configured: false };
  const db = getDb();
  const rows = db.prepare(
    `SELECT id, recipient, subject, body
       FROM email_outbox
      WHERE status IN ('queued', 'retry')
        AND attempt_count < 5
        AND (scheduled_at IS NULL OR datetime(scheduled_at) <= datetime('now','localtime'))
      ORDER BY id LIMIT ?`,
  ).all(limit) as Array<{ id: number; recipient: string; subject: string; body: string }>;
  if (!rows.length) return { sent: 0, failed: 0, configured: true };
  const transport = nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE || '').toLowerCase() === 'true',
    auth: process.env.SMTP_USER
      ? { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS || '' }
      : undefined,
    connectionTimeout: 15_000,
    socketTimeout: 30_000,
  });
  let sent = 0;
  let failed = 0;
  for (const row of rows) {
    try {
      await transport.sendMail({
        from: process.env.SMTP_FROM,
        to: row.recipient,
        subject: row.subject,
        text: row.body,
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
    }
  }
  transport.close();
  return { sent, failed, configured: true };
}

export interface InboxMessage {
  uid: number;
  from: string;
  subject: string;
  date?: string;
  text: string;
}

export async function readInbox(limit = 30): Promise<InboxMessage[]> {
  if (!imapConfigured()) return [];
  const client = new ImapFlow({
    host: String(process.env.IMAP_HOST),
    port: Number(process.env.IMAP_PORT || 993),
    secure: String(process.env.IMAP_SECURE || 'true').toLowerCase() !== 'false',
    auth: { user: String(process.env.IMAP_USER), pass: String(process.env.IMAP_PASS) },
    logger: false,
  });
  const timeoutMs = Math.max(2_000, Number(process.env.IMAP_READ_TIMEOUT_MS || 15_000));
  const timer = setTimeout(() => {
    try { void client.close(); } catch { /* timeout abort */ }
  }, timeoutMs);
  let lock: Awaited<ReturnType<typeof client.getMailboxLock>> | null = null;
  try {
    await client.connect();
    lock = await client.getMailboxLock(String(process.env.IMAP_MAILBOX || 'INBOX'));
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

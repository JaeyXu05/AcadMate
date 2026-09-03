import { Router, Response } from 'express';
import path from 'node:path';
import { existsSync } from 'node:fs';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ensureProductivitySchema, getDb } from '../db';
import { drainEmailOutbox, queueEmail, smtpConfigured } from '../services/mailer';
import { buildPresentation } from '../services/ppt';
import { runHarnessSkill } from '../harnessClient';
import { buildPersonalHarnessContext } from '../data/personalHarnessContext';

export const reportsRouter = Router();
reportsRouter.use(authMiddleware);

type PeriodType = 'daily' | 'weekly' | 'monthly';

function safeJson<T>(value: string | null | undefined, fallback: T): T {
  try { return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
}

function sqlDate(value: Date): string {
  const pad = (item: number) => String(item).padStart(2, '0');
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}`;
}

function periodBounds(period: PeriodType, reference = new Date()): { start: Date; end: Date } {
  const start = new Date(reference);
  start.setHours(0, 0, 0, 0);
  if (period === 'weekly') {
    const day = start.getDay() || 7;
    start.setDate(start.getDate() - day + 1);
  } else if (period === 'monthly') {
    start.setDate(1);
  }
  const end = new Date(start);
  if (period === 'daily') end.setDate(end.getDate() + 1);
  if (period === 'weekly') end.setDate(end.getDate() + 7);
  if (period === 'monthly') end.setMonth(end.getMonth() + 1);
  end.setMilliseconds(end.getMilliseconds() - 1);
  return { start, end };
}

function activityContext(userId: number, start: Date, end: Date) {
  const db = getDb();
  const startSql = sqlDate(start);
  const endSql = sqlDate(end);
  const events = db.prepare(
    `SELECT verb, object_type, object_id, result_json, context_json, created_at
       FROM growth_events WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
       ORDER BY created_at DESC LIMIT 100`,
  ).all(userId, startSql, endSql) as any[];
  const chats = db.prepare(
    `SELECT role, content, created_at FROM chat_history
      WHERE user_id=? AND datetime(created_at) BETWEEN datetime(?) AND datetime(?)
      ORDER BY created_at DESC LIMIT 60`,
  ).all(userId, startSql, endSql) as any[];
  const plans = db.prepare(
    `SELECT id, title, description, deliverable, acceptance_criteria, status, priority, start_at, due_at,
            estimated_minutes, actual_minutes, execution_notes, reminder_at, email_reminder, completed_at, created_at, updated_at
       FROM plans WHERE user_id=? AND datetime(created_at) <= datetime(?)
         AND (status IN ('todo','doing') OR datetime(completed_at) BETWEEN datetime(?) AND datetime(?))
       ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, due_at`,
  ).all(userId, endSql, startSql, endSql) as any[];
  const growth = db.prepare('SELECT * FROM growth_state WHERE user_id=?').get(userId) as any;
  return {
    events: events.map((item) => {
      const eventContext = safeJson<Record<string, unknown>>(item.context_json, {});
      return {
        ...item,
        result: safeJson(item.result_json, {}),
        context: eventContext,
        evidence_refs: Array.isArray(eventContext.evidence_refs)
          ? eventContext.evidence_refs.map(String)
          : [],
      };
    }),
    chats: chats.reverse(),
    plans,
    growth: growth ? {
      matched_mentors: safeJson(growth.matched_mentors, []),
      directions: safeJson(growth.directions, []),
      read_papers: safeJson(growth.read_papers, []),
      research_tasks: safeJson(growth.research_tasks, []),
      verified_experiences: safeJson(growth.verified_experiences, []),
    } : {},
  };
}

function reportBaseline(period: PeriodType, context: ReturnType<typeof activityContext>) {
  const titles = { daily: '科研日报', weekly: '科研周报', monthly: '科研月报' };
  const completed = context.plans.filter((item) => item.status === 'done');
  const pending = context.plans.filter((item) => item.status === 'todo' || item.status === 'doing');
  const completionFeedbacks = completed.filter((item) => String(item.execution_notes || '').trim());
  const evidenceRefs = [...new Set(context.events.flatMap((item) => item.evidence_refs ?? []))] as string[];
  const metrics = {
    activity_events: context.events.length,
    completion_feedbacks: completionFeedbacks.length,
    completed_plans: completed.length,
    pending_plans: pending.length,
    matched_mentors: Array.isArray((context.growth as any).matched_mentors) ? (context.growth as any).matched_mentors.length : 0,
    read_papers: Array.isArray((context.growth as any).read_papers) ? (context.growth as any).read_papers.length : 0,
  };
  return {
    title: titles[period],
    metrics,
    evidenceRefs,
  };
}

function persistReport(
  userId: number,
  period: PeriodType,
  bounds: { start: Date; end: Date },
  output: {
    title: string;
    markdown: string;
    metrics: unknown;
    evidenceRefs: unknown;
    generation: unknown;
    reviewStatus: string;
  },
) {
  const db = getDb();
  db.prepare(
    `INSERT INTO progress_reports
      (user_id, period_type, period_start, period_end, title, content_markdown, metrics_json, evidence_refs, generation_json, review_status)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(user_id, period_type, period_start, period_end) DO UPDATE SET
       title=excluded.title, content_markdown=excluded.content_markdown,
       metrics_json=excluded.metrics_json, evidence_refs=excluded.evidence_refs,
       generation_json=excluded.generation_json,
       review_status=excluded.review_status, created_at=datetime('now','localtime')`,
  ).run(
    userId,
    period,
    sqlDate(bounds.start),
    sqlDate(bounds.end),
    output.title,
    output.markdown,
    JSON.stringify(output.metrics),
    JSON.stringify(output.evidenceRefs),
    JSON.stringify(output.generation),
    output.reviewStatus,
  );
  return db.prepare(
    `SELECT * FROM progress_reports WHERE user_id=? AND period_type=? AND period_start=? AND period_end=?`,
  ).get(userId, period, sqlDate(bounds.start), sqlDate(bounds.end)) as any;
}

/** Reconcile a report whose HTTP caller timed out after A端 eventually finished. */
export function reconcileProgressReport(
  userId: number,
  payload: Record<string, unknown>,
  result: any,
): boolean {
  const period = String(payload.report_period || '') as PeriodType;
  const artifact = result?.artifact;
  const start = new Date(String(payload.period_start || ''));
  const end = new Date(String(payload.period_end || ''));
  if (!['daily', 'weekly', 'monthly'].includes(period) || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false;
  if (result?.review_status !== 'PASS' || !String(artifact?.markdown || '').trim()) return false;
  persistReport(userId, period, { start, end }, {
    title: String(artifact.title || `科研${period === 'daily' ? '日报' : period === 'weekly' ? '周报' : '月报'}`),
    markdown: String(artifact.markdown),
    metrics: artifact.metrics ?? {},
    evidenceRefs: Array.isArray(artifact.evidence_refs) ? artifact.evidence_refs : [],
    generation: artifact.generation && typeof artifact.generation === 'object'
      ? artifact.generation
      : { agent: 'progress_report_agent', status: 'completed', reconciled: true },
    reviewStatus: 'PASS',
  });
  return true;
}

async function generateReport(userId: number, period: PeriodType, reference = new Date()) {
  // The scheduler and the manual endpoint can be the first productivity
  // request after a fresh install.  Ensure all report/activity tables exist
  // before the context queries run; otherwise a missing table looks like an
  // opaque report timeout/failure.
  ensureProductivitySchema(getDb());
  const bounds = periodBounds(period, reference);
  const context = activityContext(userId, bounds.start, bounds.end);
  const personal = buildPersonalHarnessContext(userId, context.plans);
  const baseline = reportBaseline(period, context);
  const timeoutRaw = Number(process.env.REPORT_AGENT_TIMEOUT_MS || 240_000);
  const timeoutMs = Number.isFinite(timeoutRaw)
    ? Math.max(30_000, Math.min(timeoutRaw, 360_000))
    : 240_000;
  const result = await runHarnessSkill({
    userId,
    skillId: 'progress_report',
    message: `基于本周期可核验记录生成${baseline.title}`,
    query: `${period}:${sqlDate(bounds.start)}:${sqlDate(bounds.end)}`,
    timeoutMs,
    context: {
      report_period: period,
      period_start: sqlDate(bounds.start).replace(' ', 'T'),
      period_end: sqlDate(bounds.end).replace(' ', 'T'),
      current_time: sqlDate(reference).replace(' ', 'T'),
      timezone: 'Asia/Shanghai',
      progress_events: context.events,
      chat_summary: context.chats,
      plans: context.plans,
      growth: personal.trusted.growth,
      profile: personal.trusted.profile,
      personal_harness_summary: personal.summary,
      input_fingerprint: personal.fingerprint,
      input_audit: personal.audit,
    },
  });
  const artifact = result?.artifact;
  const markdown = String(artifact?.markdown || '').trim();
  if (result?.review_status !== 'PASS' || !markdown) {
    const detail = String(artifact?.error || `Review ${result?.review_status || 'UNKNOWN'}`);
    const error = new Error(`科研报告智能体未产出通过审核的报告：${detail}`);
    (error as Error & { status?: number }).status = /timeout|timed out/i.test(detail) ? 504 : 502;
    throw error;
  }
  const report = persistReport(userId, period, bounds, {
    title: String(artifact.title || baseline.title),
    markdown,
    metrics: artifact.metrics ?? baseline.metrics,
    evidenceRefs: Array.isArray(artifact.evidence_refs) ? artifact.evidence_refs : baseline.evidenceRefs,
    generation: artifact.generation ?? { agent: 'progress_report_agent', status: 'completed' },
    reviewStatus: 'PASS',
  });
  console.log(`[progress_report] user=${userId} period=${period} source=progress_report_agent run=${result.run_id}`);
  return report;
}

function reportFreshness(row: any, userId: number): { is_stale: boolean; newer_records_count: number } {
  const db = getDb();
  const reportTime = String(row.created_at || '');
  if (!reportTime) return { is_stale: false, newer_records_count: 0 };
  const candidates = [
    db.prepare('SELECT MAX(created_at) AS value FROM plans WHERE user_id=?').get(userId) as any,
    db.prepare('SELECT MAX(updated_at) AS value FROM plans WHERE user_id=?').get(userId) as any,
    db.prepare('SELECT MAX(created_at) AS value FROM chat_history WHERE user_id=?').get(userId) as any,
    db.prepare('SELECT MAX(created_at) AS value FROM growth_events WHERE user_id=?').get(userId) as any,
    db.prepare('SELECT updated_at AS value FROM growth_state WHERE user_id=?').get(userId) as any,
  ].map((item) => String(item?.value || '')).filter(Boolean);
  const newer = candidates.filter((value) => value > reportTime);
  return { is_stale: newer.length > 0, newer_records_count: newer.length };
}

function evidenceSummary(refs: unknown[]): string {
  const values = Array.isArray(refs) ? refs.map(String) : [];
  const plan = values.filter((item) => item.startsWith('plan:')).length;
  const activity = values.filter((item) => item.startsWith('activity:')).length;
  const chat = values.filter((item) => item.startsWith('chat:')).length;
  const external = values.length - plan - activity - chat;
  const parts = [
    plan ? `${plan} 项计划记录` : '',
    activity ? `${activity} 条科研活动` : '',
    chat ? `${chat} 条讨论记录` : '',
    external ? `${external} 条外部证据` : '',
  ].filter(Boolean);
  return parts.length ? `依据：${parts.join('、')}` : '依据：本周期暂无可引用记录';
}

function presentationVisualData(userId: number, report: any): Record<string, unknown> {
  const db = getDb();
  const evidenceRefs = safeJson(report.evidence_refs, [] as string[]).map(String);
  const evidence = {
    plan: evidenceRefs.filter((item) => item.startsWith('plan:')).length,
    activity: evidenceRefs.filter((item) => item.startsWith('activity:')).length,
    chat: evidenceRefs.filter((item) => item.startsWith('chat:')).length,
    other: evidenceRefs.filter((item) => !/^(plan|activity|chat):/.test(item)).length,
  };
  const plans = db.prepare(
    `SELECT title,status,priority,due_at,estimated_minutes,actual_minutes,completed_at
       FROM plans WHERE user_id=? AND datetime(created_at) <= datetime(?)
       ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END, due_at, id DESC LIMIT 6`,
  ).all(userId, String(report.period_end || '')) as any[];
  const historyRows = db.prepare(
    `SELECT period_end,metrics_json FROM progress_reports
       WHERE user_id=? AND period_type=? AND datetime(period_end) <= datetime(?)
       ORDER BY datetime(period_end) DESC LIMIT 7`,
  ).all(userId, String(report.period_type || 'daily'), String(report.period_end || '')) as any[];
  const history = historyRows.reverse().map((item) => {
    const metrics = safeJson<Record<string, unknown>>(item.metrics_json, {});
    return {
      label: String(item.period_end || '').slice(5, 10) || '本期',
      activity_events: Number(metrics.activity_events || 0),
      completed_plans: Number(metrics.completed_plans || 0),
      pending_plans: Number(metrics.pending_plans || 0),
    };
  });
  return {
    metrics: safeJson<Record<string, unknown>>(report.metrics_json, {}),
    period: { start: String(report.period_start || ''), end: String(report.period_end || ''), type: String(report.period_type || '') },
    plans,
    history,
    evidence,
  };
}

function mapReport(row: any, userId?: number) {
  const evidenceRefs = safeJson(row.evidence_refs, [] as string[]);
  return {
    ...row,
    metrics: safeJson(row.metrics_json, {}),
    evidence_refs: evidenceRefs,
    evidence_summary: evidenceSummary(evidenceRefs),
    generation: safeJson(row.generation_json, {}),
    ...(userId ? reportFreshness(row, userId) : { is_stale: false, newer_records_count: 0 }),
  };
}

function mapPresentation(row: any) {
  return {
    ...row,
    download_url: row.status === 'succeeded' ? `/api/reports/presentations/${row.id}/download` : null,
  };
}

function fail(res: Response, err: unknown, fallback: string): void {
  const detail = err instanceof Error ? err.message : String(err || '');
  const status = Number((err as { status?: number })?.status);
  res.status(status >= 400 && status < 600 ? status : 500).json({ message: detail ? `${fallback}：${detail}` : fallback });
}

reportsRouter.get('/preferences', (req: AuthRequest, res: Response) => {
  try {
    const db = getDb();
    ensureProductivitySchema(db);
    db.prepare('INSERT OR IGNORE INTO report_preferences (user_id) VALUES (?)').run(req.userId!);
    const row = db.prepare('SELECT * FROM report_preferences WHERE user_id=?').get(req.userId!) as any;
    res.json({ ...row, daily_enabled: Boolean(row.daily_enabled), weekly_enabled: Boolean(row.weekly_enabled), monthly_enabled: Boolean(row.monthly_enabled), email_enabled: Boolean(row.email_enabled), smtp_configured: smtpConfigured() });
  } catch (err) {
    fail(res, err, '报告设置加载失败');
  }
});

reportsRouter.put('/preferences', (req: AuthRequest, res: Response) => {
  const body = req.body ?? {};
  const weeklyDay = Math.max(0, Math.min(6, Number(body.weekly_day ?? 5)));
  const monthlyDay = Math.max(1, Math.min(28, Number(body.monthly_day ?? 1)));
  const dailyTime = /^([01]\d|2[0-3]):[0-5]\d$/.test(String(body.daily_time || '')) ? String(body.daily_time) : '20:00';
  getDb().prepare(
    `INSERT INTO report_preferences
      (user_id,daily_enabled,weekly_enabled,monthly_enabled,email_enabled,daily_time,weekly_day,monthly_day,timezone)
     VALUES (?,?,?,?,?,?,?,?,?)
     ON CONFLICT(user_id) DO UPDATE SET
       daily_enabled=excluded.daily_enabled, weekly_enabled=excluded.weekly_enabled,
       monthly_enabled=excluded.monthly_enabled, email_enabled=excluded.email_enabled,
       daily_time=excluded.daily_time, weekly_day=excluded.weekly_day,
       monthly_day=excluded.monthly_day, timezone=excluded.timezone,
       updated_at=datetime('now','localtime')`,
  ).run(req.userId!, body.daily_enabled ? 1 : 0, body.weekly_enabled ? 1 : 0, body.monthly_enabled ? 1 : 0, body.email_enabled ? 1 : 0, dailyTime, weeklyDay, monthlyDay, String(body.timezone || 'Asia/Shanghai'));
  res.json({ ok: true });
});

reportsRouter.get('/', (req: AuthRequest, res: Response) => {
  try {
    ensureProductivitySchema(getDb());
    const rows = getDb().prepare("SELECT * FROM progress_reports WHERE user_id=? AND review_status='PASS' ORDER BY period_end DESC, id DESC").all(req.userId!);
    res.json((rows as any[]).map((row) => mapReport(row, req.userId!)));
  } catch (err) {
    fail(res, err, '报告列表加载失败');
  }
});

reportsRouter.post('/generate', async (req: AuthRequest, res: Response) => {
  const period = String(req.body?.period_type || 'weekly') as PeriodType;
  if (!['daily', 'weekly', 'monthly'].includes(period)) {
    res.status(400).json({ message: 'period_type 必须是 daily、weekly 或 monthly' });
    return;
  }
  try {
    const report = await generateReport(req.userId!, period);
    if (req.body?.send_email) {
      const user = getDb().prepare('SELECT email FROM users WHERE id=?').get(req.userId!) as { email: string };
      queueEmail({ userId: req.userId!, recipient: user.email, subject: report.title, body: report.content_markdown, kind: `report:${period}` });
      void drainEmailOutbox();
    }
    res.json(mapReport(report, req.userId!));
  } catch (err) {
    fail(res, err, '报告智能体生成失败');
  }
});

reportsRouter.post('/:reportId/presentation', async (req: AuthRequest, res: Response) => {
  const reportId = Number(req.params.reportId);
  if (!Number.isInteger(reportId) || reportId <= 0) {
    res.status(400).json({ message: '报告 ID 无效' });
    return;
  }
  const db = getDb();
  const report = db.prepare("SELECT * FROM progress_reports WHERE id=? AND user_id=? AND review_status='PASS'").get(reportId, req.userId!) as any;
  if (!report) { res.status(404).json({ message: '报告不存在' }); return; }
  const template = ['group_meeting', 'weekly', 'monthly', 'literature_review'].includes(String(req.body?.template))
    ? String(req.body.template) : 'group_meeting';
  const slideCount = Math.max(3, Math.min(20, Number(req.body?.slide_count || 8)));
  const title = String(req.body?.title || report.title).trim().slice(0, 200) || report.title;
  const created = db.prepare(
    `INSERT INTO presentation_jobs (user_id, report_id, status, template, slide_count, title)
     VALUES (?, ?, 'queued', ?, ?, ?)`,
  ).run(req.userId!, reportId, template, slideCount, title);
  const jobId = Number(created.lastInsertRowid);
  const outputPath = path.join(process.cwd(), 'generated', 'presentations', `${req.userId}-${reportId}-${jobId}.pptx`);
  db.prepare('UPDATE presentation_jobs SET status=\'generating\', file_path=? WHERE id=? AND user_id=?').run(outputPath, jobId, req.userId!);
  void buildPresentation({
    title,
    template,
    slideCount,
    markdown: String(report.content_markdown || ''),
    evidenceRefs: safeJson(report.evidence_refs, []),
    visualData: presentationVisualData(req.userId!, report),
  }, outputPath).then(() => {
    db.prepare("UPDATE presentation_jobs SET status='succeeded', completed_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(jobId, req.userId!);
  }).catch((error: unknown) => {
    db.prepare("UPDATE presentation_jobs SET status='failed', error=?, completed_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(error instanceof Error ? error.message : String(error), jobId, req.userId!);
  });
  const job = db.prepare('SELECT * FROM presentation_jobs WHERE id=? AND user_id=?').get(jobId, req.userId!);
  res.status(202).json(mapPresentation(job));
});

reportsRouter.get('/presentations/:id', (req: AuthRequest, res: Response) => {
  const id = Number(req.params.id);
  const job = Number.isInteger(id) ? getDb().prepare('SELECT * FROM presentation_jobs WHERE id=? AND user_id=?').get(id, req.userId!) as any : undefined;
  if (!job) { res.status(404).json({ message: 'PPT 任务不存在' }); return; }
  res.json(mapPresentation(job));
});

reportsRouter.get('/presentations/:id/download', (req: AuthRequest, res: Response) => {
  const id = Number(req.params.id);
  const job = Number.isInteger(id) ? getDb().prepare('SELECT * FROM presentation_jobs WHERE id=? AND user_id=?').get(id, req.userId!) as any : undefined;
  if (!job) { res.status(404).json({ message: 'PPT 任务不存在' }); return; }
  if (job.status !== 'succeeded' || !job.file_path || !existsSync(job.file_path)) { res.status(409).json({ message: 'PPT 尚未生成完成' }); return; }
  res.download(job.file_path, `${String(job.title || '科研报告').replace(/[\\/:*?"<>|]/g, '_')}.pptx`);
});

reportsRouter.get('/outbox', (req: AuthRequest, res: Response) => {
  const rows = getDb().prepare('SELECT id,recipient,subject,kind,status,scheduled_at,sent_at,error,created_at FROM email_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100').all(req.userId!);
  res.json({ smtp_configured: smtpConfigured(), items: rows });
});

let reportSchedulerRunning = false;

function scheduledTimeReached(value: unknown, now: Date): boolean {
  const match = /^(\d{2}):(\d{2})$/.exec(String(value || ''));
  if (!match) return false;
  const target = Number(match[1]) * 60 + Number(match[2]);
  return now.getHours() * 60 + now.getMinutes() >= target;
}

export async function runReportScheduler(): Promise<void> {
  if (reportSchedulerRunning) return;
  reportSchedulerRunning = true;
  try {
    const db = getDb();
    ensureProductivitySchema(db);
    const preferences = db.prepare(
      `SELECT p.*, u.email FROM report_preferences p JOIN users u ON u.id=p.user_id
        WHERE p.email_enabled=1`,
    ).all() as any[];
    const now = new Date();
    for (const pref of preferences) {
      const due: PeriodType[] = [];
      const timeReached = scheduledTimeReached(pref.daily_time, now);
      if (timeReached && pref.daily_enabled) due.push('daily');
      if (timeReached && pref.weekly_enabled && now.getDay() === pref.weekly_day) due.push('weekly');
      if (timeReached && pref.monthly_enabled && now.getDate() === pref.monthly_day) due.push('monthly');
      for (const period of due) {
      const bounds = periodBounds(period, now);
      const existing = db.prepare("SELECT * FROM progress_reports WHERE user_id=? AND period_type=? AND period_start=? AND period_end=? AND review_status='PASS'").get(pref.user_id, period, sqlDate(bounds.start), sqlDate(bounds.end)) as any;
      let report = existing;
      if (!report) {
        try {
          report = await generateReport(pref.user_id, period, now);
        } catch (err) {
          const detail = err instanceof Error ? err.message : String(err);
          console.error(`[progress_report_agent] user=${pref.user_id} period=${period} failed: ${detail}`);
          continue;
        }
      }
      const kind = `report:${period}:${sqlDate(bounds.start).slice(0, 10)}`;
      const queued = db.prepare('SELECT id FROM email_outbox WHERE user_id=? AND kind=?').get(pref.user_id, kind);
      if (!queued) {
        queueEmail({ userId: pref.user_id, recipient: pref.email, subject: report.title, body: report.content_markdown, kind });
      }
    }
    }
    await drainEmailOutbox();
  } finally {
    reportSchedulerRunning = false;
  }
}

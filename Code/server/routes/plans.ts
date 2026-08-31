import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ensureProductivitySchema, getDb } from '../db';
import { loadTrustedAgentContext } from '../data/growthStore';
import { agentBase, probeAgent, runHarnessSkill } from '../harnessClient';
import { drainEmailOutbox, queueEmail } from '../services/mailer';

export const plansRouter = Router();
plansRouter.use(authMiddleware);

function fail(res: Response, err: unknown, fallback: string): void {
  const detail = err instanceof Error ? err.message : String(err || '');
  res.status(500).json({ message: detail ? `${fallback}：${detail}` : fallback });
}

function listPlans(userId: number): any[] {
  return getDb().prepare(
    `SELECT * FROM plans WHERE user_id=?
      ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END,
               CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
               due_at, id DESC`,
  ).all(userId) as any[];
}

function normalizePlan(body: any) {
  const status = ['todo', 'doing', 'done', 'cancelled'].includes(String(body.status)) ? String(body.status) : 'todo';
  const priority = ['low', 'medium', 'high'].includes(String(body.priority)) ? String(body.priority) : 'medium';
  return {
    title: String(body.title || '').trim().slice(0, 200),
    description: String(body.description || '').trim().slice(0, 4000),
    status,
    priority,
    startAt: body.start_at ? String(body.start_at) : null,
    dueAt: body.due_at ? String(body.due_at) : null,
    estimatedMinutes: Math.max(5, Math.min(10080, Number(body.estimated_minutes || 60))),
    actualMinutes: Math.max(0, Math.min(10080, Number(body.actual_minutes || 0))),
    reminderAt: body.reminder_at ? String(body.reminder_at) : null,
    emailReminder: body.email_reminder ? 1 : 0,
  };
}

plansRouter.get('/', (req: AuthRequest, res: Response) => {
  try {
    ensureProductivitySchema(getDb());
    res.json(listPlans(req.userId!) ?? []);
  } catch (err) {
    fail(res, err, '计划加载失败');
  }
});

plansRouter.post('/', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const plan = normalizePlan(req.body ?? {});
  if (!plan.title) { res.status(400).json({ message: '计划标题不能为空' }); return; }
  const result = getDb().prepare(
    `INSERT INTO plans
      (user_id,title,description,status,priority,start_at,due_at,estimated_minutes,actual_minutes,reminder_at,email_reminder,source,completed_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,'user',CASE WHEN ?='done' THEN datetime('now','localtime') ELSE NULL END)`,
  ).run(req.userId!, plan.title, plan.description, plan.status, plan.priority, plan.startAt, plan.dueAt, plan.estimatedMinutes, plan.actualMinutes, plan.reminderAt, plan.emailReminder, plan.status);
  res.status(201).json(getDb().prepare('SELECT * FROM plans WHERE id=? AND user_id=?').get(Number(result.lastInsertRowid), req.userId!));
});

plansRouter.put('/:id', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const id = Number(req.params.id);
  const plan = normalizePlan(req.body ?? {});
  if (!id || !plan.title) { res.status(400).json({ message: '计划参数无效' }); return; }
  const result = getDb().prepare(
    `UPDATE plans SET title=?,description=?,status=?,priority=?,start_at=?,due_at=?,
      estimated_minutes=?,actual_minutes=?,reminder_at=?,email_reminder=?,
      completed_at=CASE WHEN ?='done' THEN COALESCE(completed_at,datetime('now','localtime')) ELSE NULL END,
      updated_at=datetime('now','localtime')
      WHERE id=? AND user_id=?`,
  ).run(plan.title, plan.description, plan.status, plan.priority, plan.startAt, plan.dueAt, plan.estimatedMinutes, plan.actualMinutes, plan.reminderAt, plan.emailReminder, plan.status, id, req.userId!);
  if (!result.changes) { res.status(404).json({ message: '计划不存在' }); return; }
  res.json(getDb().prepare('SELECT * FROM plans WHERE id=? AND user_id=?').get(id, req.userId!));
});

plansRouter.delete('/:id', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const result = getDb().prepare('DELETE FROM plans WHERE id=? AND user_id=?').run(Number(req.params.id), req.userId!);
  if (!result.changes) { res.status(404).json({ message: '计划不存在' }); return; }
  res.status(204).end();
});

plansRouter.post('/suggest', async (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const plans = listPlans(req.userId!);
  const trusted = loadTrustedAgentContext(req.userId!);
  if (agentBase() && await probeAgent(2500)) {
    try {
      const result = await runHarnessSkill({
        userId: req.userId!, skillId: 'plan_coach', message: '基于历史交流和科研成长状态提出计划建议',
        timeoutMs: Math.max(60_000, Number(process.env.PLAN_AGENT_TIMEOUT_MS || 150_000)),
        context: { plans, growth: trusted.growth, profile: trusted.profile },
      });
      if (result?.review_status === 'PASS') { res.json(result.artifact); return; }
    } catch { /* deterministic fallback below */ }
  }
  const open = plans.filter((item) => item.status === 'todo' || item.status === 'doing');
  const suggestions = [];
  if (open.length > 5) suggestions.push({ kind: 'workload', text: '开放计划超过 5 项，建议保留最多 3 项本周核心交付。' });
  if (open.some((item) => !item.due_at)) suggestions.push({ kind: 'deadline', text: '给未设置截止时间的计划补充日期与验收标准。' });
  if (!suggestions.length) suggestions.push({ kind: 'focus', text: '优先完成最早到期且有明确验收标准的一项。' });
  res.json({ type: 'plan_coach', suggestions, evidence_refs: [] });
});

export async function runPlanReminderScheduler(): Promise<void> {
  const db = getDb();
  ensureProductivitySchema(db);
  const due = db.prepare(
    `SELECT p.*, u.email FROM plans p JOIN users u ON u.id=p.user_id
      WHERE p.email_reminder=1 AND p.status IN ('todo','doing') AND p.reminder_at IS NOT NULL
        AND datetime(p.reminder_at) <= datetime('now','localtime')`,
  ).all() as any[];
  for (const plan of due) {
    const kind = `plan:${plan.id}`;
    const exists = db.prepare(`SELECT id FROM email_outbox WHERE user_id=? AND kind=?`).get(plan.user_id, kind);
    if (exists) continue;
    queueEmail({
      userId: plan.user_id,
      recipient: plan.email,
      subject: `科研计划提醒：${plan.title}`,
      body: `计划：${plan.title}\n状态：${plan.status}\n截止：${plan.due_at || '未设置'}\n\n建议先确认本次工作的可验收输出与证据位置。`,
      kind,
    });
  }
  await drainEmailOutbox();
}

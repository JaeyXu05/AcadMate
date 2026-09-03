import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ensureProductivitySchema, getDb } from '../db';
import { buildPersonalHarnessContext } from '../data/personalHarnessContext';
import { appendGrowthEvent } from '../data/growthStore';
import { findProductivityRun, findProductivityRunById, saveProductivityRun } from '../data/productivityRuns';
import { agentBase, cancelHarnessRun, fetchHarnessEvents, fetchHarnessResult, launchHarnessSkill, probeAgentLiveness } from '../harnessClient';
import { drainEmailOutbox, queueEmail } from '../services/mailer';

export const plansRouter = Router();
plansRouter.use(authMiddleware);

function safeJsonArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean).slice(0, 4);
  if (typeof value !== 'string' || !value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String).map((item) => item.trim()).filter(Boolean).slice(0, 4) : [];
  } catch { return []; }
}

function mapPlan(row: any): any {
  return row ? { ...row, acceptance_criteria: safeJsonArray(row.acceptance_criteria) } : row;
}

function localDateTime(value = new Date()): string {
  const pad = (item: number) => String(item).padStart(2, '0');
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

function fail(res: Response, err: unknown, fallback: string): void {
  const detail = err instanceof Error ? err.message : String(err || '');
  res.status(500).json({ message: detail ? `${fallback}：${detail}` : fallback });
}

function listPlans(userId: number): any[] {
  const rows = getDb().prepare(
    `SELECT * FROM plans WHERE user_id=?
      ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'todo' THEN 1 ELSE 2 END,
               parent_plan_id IS NOT NULL, sequence, CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
               due_at, id DESC`,
  ).all(userId) as any[];
  return rows.map(mapPlan);
}

function fallbackPlanArtifact(plans: any[]): Record<string, unknown> {
  const open = plans.filter((item) => item.status === 'todo' || item.status === 'doing');
  const now = new Date();
  const planDrafts = open.slice(0, 3).map((item, index) => {
    const start = new Date(now.getTime() + (index * 75 + 5) * 60_000);
    const due = new Date(start.getTime() + Math.max(30, Math.min(Number(item.estimated_minutes || 60), 120)) * 60_000);
    return { title: `${item.title}：第 ${index + 1} 阶段`, description: `目标：将“${item.title}”收敛为一次可验收的工作时段。\n交付物：一份记录本阶段范围、关键要点和下一步的学习或研究笔记。\n验收标准：明确本阶段只处理一个主题；记录至少 3 条可复核要点；写出一个下一步问题。`, deliverable: '一份结构化学习或研究笔记', acceptance_criteria: ['明确本阶段只处理一个主题', '记录至少 3 条可复核要点', '写出一个下一步问题'], priority: item.priority, start_at: localDateTime(start), due_at: localDateTime(due), estimated_minutes: Math.max(30, Math.min(Number(item.estimated_minutes || 60), 120)), actual_minutes: 0, reminder_at: localDateTime(new Date(start.getTime() - 15 * 60_000)), email_reminder: item.email_reminder ? 1 : 0, source_plan_id: item.id, sequence: index + 1 };
  });
  return { type: 'plan_coach', planning_summary: open.length ? '智能规划暂不可用，已依据当前计划生成可执行的降级拆解。' : '当前没有开放计划，建议先建立一个可验收的研究目标。', capacity_assessment: open.length > 5 ? '开放计划较多，建议先保留不超过 3 项核心交付。' : '当前只能依据已记录计划进行容量判断。', personalization_basis: open.length ? ['已使用当前开放计划'] : ['当前缺少开放计划和个人研究背景'], plan_drafts: planDrafts, milestones: planDrafts, suggestions: planDrafts.map((item) => ({ kind: 'milestone', text: item.title, plan_id: item.source_plan_id })), risks: ['当前结果为模型不可用时的降级方案，请在应用前复核。'], generation: { agent: 'plan_coach', status: 'fallback', reason: 'Harness unavailable' }, evidence_refs: [] };
}

function jobResponse(job: ReturnType<typeof findProductivityRun>, events: any[] = []) {
  if (!job) return null;
  return { run_id: job.runId, status: job.status, artifact: Object.keys(job.artifact).length ? job.artifact : null, audit: job.audit, error: job.error, events };
}

function isFallbackPlanResult(job: ReturnType<typeof findProductivityRun>): boolean {
  if (!job || job.skillId !== 'plan_coach') return false;
  const generation = job.artifact?.generation;
  return Boolean(
    generation
    && typeof generation === 'object'
    && (generation as Record<string, unknown>).status === 'fallback',
  );
}

function normalizePlan(body: any) {
  const status = ['todo', 'doing', 'done', 'cancelled'].includes(String(body.status)) ? String(body.status) : 'todo';
  const priority = ['low', 'medium', 'high'].includes(String(body.priority)) ? String(body.priority) : 'medium';
  const parentPlanId = Number(body.parent_plan_id);
  const sequence = Number(body.sequence);
  return {
    parentPlanId: Number.isInteger(parentPlanId) && parentPlanId > 0 ? parentPlanId : null,
    title: String(body.title || '').trim().slice(0, 200),
    description: String(body.description || '').trim().slice(0, 4000),
    deliverable: String(body.deliverable || '').trim().slice(0, 600),
    acceptanceCriteria: safeJsonArray(body.acceptance_criteria),
    sequence: Number.isInteger(sequence) && sequence > 0 && sequence <= 99 ? sequence : null,
    status,
    priority,
    startAt: body.start_at ? String(body.start_at) : null,
    dueAt: body.due_at ? String(body.due_at) : null,
    estimatedMinutes: Math.max(5, Math.min(10080, Number(body.estimated_minutes || 60))),
    actualMinutes: Math.max(0, Math.min(10080, Number(body.actual_minutes || 0))),
    executionNotes: String(body.execution_notes || '').trim().slice(0, 4000),
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
      (user_id,parent_plan_id,title,description,deliverable,acceptance_criteria,sequence,status,priority,start_at,due_at,estimated_minutes,actual_minutes,execution_notes,reminder_at,email_reminder,source,completed_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'user',CASE WHEN ?='done' THEN datetime('now','localtime') ELSE NULL END)`,
  ).run(req.userId!, plan.parentPlanId, plan.title, plan.description, plan.deliverable, JSON.stringify(plan.acceptanceCriteria), plan.sequence, plan.status, plan.priority, plan.startAt, plan.dueAt, plan.estimatedMinutes, plan.actualMinutes, plan.executionNotes, plan.reminderAt, plan.emailReminder, plan.status);
  res.status(201).json(mapPlan(getDb().prepare('SELECT * FROM plans WHERE id=? AND user_id=?').get(Number(result.lastInsertRowid), req.userId!)));
});

plansRouter.put('/:id', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const id = Number(req.params.id);
  const plan = normalizePlan(req.body ?? {});
  if (!id || !plan.title) { res.status(400).json({ message: '计划参数无效' }); return; }
  const result = getDb().prepare(
    `UPDATE plans SET parent_plan_id=?,title=?,description=?,deliverable=?,acceptance_criteria=?,sequence=?,status=?,priority=?,start_at=?,due_at=?,
      estimated_minutes=?,actual_minutes=?,execution_notes=?,reminder_at=?,email_reminder=?,
      completed_at=CASE WHEN ?='done' THEN COALESCE(completed_at,datetime('now','localtime')) ELSE NULL END,
      updated_at=datetime('now','localtime')
      WHERE id=? AND user_id=?`,
  ).run(plan.parentPlanId, plan.title, plan.description, plan.deliverable, JSON.stringify(plan.acceptanceCriteria), plan.sequence, plan.status, plan.priority, plan.startAt, plan.dueAt, plan.estimatedMinutes, plan.actualMinutes, plan.executionNotes, plan.reminderAt, plan.emailReminder, plan.status, id, req.userId!);
  if (!result.changes) { res.status(404).json({ message: '计划不存在' }); return; }
  res.json(mapPlan(getDb().prepare('SELECT * FROM plans WHERE id=? AND user_id=?').get(id, req.userId!)));
});

plansRouter.delete('/:id', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const result = getDb().prepare('DELETE FROM plans WHERE id=? AND user_id=?').run(Number(req.params.id), req.userId!);
  if (!result.changes) { res.status(404).json({ message: '计划不存在' }); return; }
  res.status(204).end();
});

/** Record a researcher-facing completion outcome instead of silently flipping a status. */
plansRouter.post('/:id/complete', (req: AuthRequest, res: Response) => {
  try {
    ensureProductivitySchema(getDb());
    const id = Number(req.params.id);
    const notes = String(req.body?.execution_notes || '').trim().slice(0, 4000);
    const actualMinutes = Math.max(1, Math.min(10080, Number(req.body?.actual_minutes || 0)));
    if (!Number.isInteger(id) || id <= 0) { res.status(400).json({ message: '计划参数无效' }); return; }
    if (notes.length < 4) { res.status(400).json({ message: '请记录实际完成结果、产出或遇到的问题（至少 4 个字）' }); return; }
    if (!Number.isFinite(actualMinutes)) { res.status(400).json({ message: '请填写实际投入时间' }); return; }
    const existing = getDb().prepare('SELECT id,title FROM plans WHERE id=? AND user_id=?').get(id, req.userId!) as { id: number; title: string } | undefined;
    if (!existing) { res.status(404).json({ message: '计划不存在' }); return; }
    getDb().prepare(
      `UPDATE plans SET status='done', actual_minutes=?, execution_notes=?, completed_at=datetime('now','localtime'), updated_at=datetime('now','localtime') WHERE id=? AND user_id=?`,
    ).run(actualMinutes, notes, id, req.userId!);
    appendGrowthEvent(req.userId!, {
      verb: 'plan_completed', objectType: 'research_plan', objectId: String(id),
      result: { title: existing.title, actual_minutes: actualMinutes, execution_notes: notes },
      context: { evidence_refs: [`plan:${id}`], source: 'completion_feedback' },
    });
    res.json(mapPlan(getDb().prepare('SELECT * FROM plans WHERE id=? AND user_id=?').get(id, req.userId!)));
  } catch (err) {
    fail(res, err, '完成反馈保存失败');
  }
});

plansRouter.post('/suggest', async (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const plans = listPlans(req.userId!);
  const personal = buildPersonalHarnessContext(req.userId!, plans);
  const cached = findProductivityRun(req.userId!, 'plan_coach', personal.fingerprint);
  // A labelled fallback is useful to display once, but it must never suppress
  // a new model attempt after the upstream output/configuration is corrected.
  if (cached && ['queued', 'pending', 'running', 'succeeded'].includes(cached.status) && !isFallbackPlanResult(cached)) {
    res.status(cached.status === 'succeeded' ? 200 : 202).json(jobResponse(cached)); return;
  }
  if (agentBase() && await probeAgentLiveness(2500)) {
    try {
      const created = await launchHarnessSkill({
        userId: req.userId!, skillId: 'plan_coach', message: '基于个人科研历史、当前计划与可核验记录提出阶段化计划建议',
        timeoutMs: 15_000,
        context: {
          plans,
          growth: personal.trusted.growth,
          profile: personal.trusted.profile,
          personal_harness_summary: personal.summary,
          input_fingerprint: personal.fingerprint,
          input_audit: personal.audit,
          current_time: localDateTime(),
          timezone: 'Asia/Shanghai',
        },
      });
      const job = saveProductivityRun({ userId: req.userId!, skillId: 'plan_coach', fingerprint: personal.fingerprint, runId: String(created.run_id), status: String(created.status || 'queued'), artifact: {}, audit: personal.audit, error: null });
      res.status(202).json(jobResponse(job)); return;
    } catch (err) {
      const artifact = fallbackPlanArtifact(plans);
      const job = saveProductivityRun({ userId: req.userId!, skillId: 'plan_coach', fingerprint: personal.fingerprint, runId: null, status: 'succeeded', artifact, audit: personal.audit, error: err instanceof Error ? err.message : String(err) });
      res.json(jobResponse(job)); return;
    }
  }
  const artifact = fallbackPlanArtifact(plans);
  const job = saveProductivityRun({ userId: req.userId!, skillId: 'plan_coach', fingerprint: personal.fingerprint, runId: null, status: 'succeeded', artifact, audit: personal.audit, error: 'Mentor Agent unavailable' });
  res.json(jobResponse(job));
});

plansRouter.get('/suggest/:runId', async (req: AuthRequest, res: Response) => {
  const job = findProductivityRunById(req.userId!, 'plan_coach', String(req.params.runId));
  if (!job) { res.status(404).json({ message: '计划任务不存在' }); return; }
  if (job.runId && ['queued', 'pending', 'running'].includes(job.status)) {
    try {
      const result = await fetchHarnessResult(job.runId);
      job.status = String(result.status || job.status);
      if (['succeeded', 'failed', 'cancelled'].includes(job.status)) {
        job.artifact = result?.artifact && typeof result.artifact === 'object' ? result.artifact : {};
        job.error = result?.artifact?.generation?.reason ? String(result.artifact.generation.reason) : null;
      }
      saveProductivityRun(job);
    } catch (err) { job.error = err instanceof Error ? err.message : String(err); }
  }
  res.json(jobResponse(job));
});

plansRouter.get('/suggest/:runId/events', async (req: AuthRequest, res: Response) => {
  const job = findProductivityRunById(req.userId!, 'plan_coach', String(req.params.runId));
  if (!job?.runId) { res.status(404).json({ message: '计划任务不存在' }); return; }
  const after = Number(req.query.after_sequence || 0);
  const events = await fetchHarnessEvents(job.runId, Number.isFinite(after) && after > 0 ? after : undefined);
  res.json({ status: job.status, events });
});

plansRouter.post('/suggest/:runId/cancel', async (req: AuthRequest, res: Response) => {
  const job = findProductivityRunById(req.userId!, 'plan_coach', String(req.params.runId));
  if (!job?.runId) { res.status(404).json({ message: '计划任务不存在' }); return; }
  try { await cancelHarnessRun(job.runId); job.status = 'cancelled'; saveProductivityRun(job); res.json(jobResponse(job)); }
  catch (err) { fail(res, err, '计划任务取消失败'); }
});

plansRouter.post('/suggest/apply', (req: AuthRequest, res: Response) => {
  try {
    ensureProductivitySchema(getDb());
    const rows = Array.isArray(req.body?.plan_drafts) ? req.body.plan_drafts.slice(0, 8) : [];
    if (!rows.length) { res.status(400).json({ message: '没有可应用的计划拆解' }); return; }
    const create = getDb().prepare(
      `INSERT INTO plans
        (user_id,parent_plan_id,title,description,deliverable,acceptance_criteria,sequence,status,priority,start_at,due_at,estimated_minutes,actual_minutes,reminder_at,email_reminder,source)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'plan_coach')`,
    );
    const existingParent = getDb().prepare('SELECT id FROM plans WHERE id=? AND user_id=?');
    const existingTitle = getDb().prepare("SELECT id FROM plans WHERE user_id=? AND title=? AND status IN ('todo','doing') LIMIT 1");
    const createdIds = getDb().transaction(() => rows.reduce<number[]>((ids, raw) => {
      const plan = normalizePlan(raw);
      if (!plan.title || existingTitle.get(req.userId!, plan.title)) return ids;
      const parent = plan.parentPlanId && existingParent.get(plan.parentPlanId, req.userId!) ? plan.parentPlanId : null;
      const result = create.run(req.userId!, parent, plan.title, plan.description, plan.deliverable, JSON.stringify(plan.acceptanceCriteria), plan.sequence, 'todo', plan.priority, plan.startAt, plan.dueAt, plan.estimatedMinutes, 0, plan.reminderAt, plan.emailReminder);
      ids.push(Number(result.lastInsertRowid));
      return ids;
    }, []))();
    if (!createdIds.length) { res.status(409).json({ message: '这些拆解任务已存在，未重复创建' }); return; }
    const placeholders = createdIds.map(() => '?').join(',');
    const created = getDb().prepare(`SELECT * FROM plans WHERE user_id=? AND id IN (${placeholders}) ORDER BY sequence,id`).all(req.userId!, ...createdIds);
    res.status(201).json({ created: (created as any[]).map(mapPlan) });
  } catch (err) {
    fail(res, err, '计划拆解应用失败');
  }
});

plansRouter.get('/reminders', (req: AuthRequest, res: Response) => {
  try {
    ensureProductivitySchema(getDb());
    const rows = getDb().prepare(
      `SELECT id,title,status,due_at,reminder_at,email_reminder,parent_plan_id
         FROM plans WHERE user_id=? AND status IN ('todo','doing') AND reminder_at IS NOT NULL
          AND datetime(reminder_at) <= datetime('now','localtime','+24 hours')
         ORDER BY datetime(reminder_at), id LIMIT 20`,
    ).all(req.userId!);
    const now = new Date();
    res.json((rows as any[]).map((item) => ({
      ...item,
      state: new Date(String(item.reminder_at).replace(' ', 'T')).getTime() <= now.getTime() ? 'due' : 'upcoming',
    })));
  } catch (err) {
    fail(res, err, '提醒加载失败');
  }
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

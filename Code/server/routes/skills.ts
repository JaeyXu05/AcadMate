import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { getDb } from '../db';

export const skillsRouter = Router();
skillsRouter.use(authMiddleware);

function parseId(value: string): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function jsonArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).map((item) => item.trim()).filter(Boolean).slice(0, 32);
  return [];
}

function mapSkill(row: any) {
  return {
    ...row,
    allowed_tools: parseJsonArray(row.allowed_tools),
    permissions: parseJsonArray(row.permissions),
  };
}

function parseJsonArray(value: unknown): string[] {
  if (typeof value !== 'string') return [];
  try { return jsonArray(JSON.parse(value)); } catch { return []; }
}

function ownSkill(userId: number, id: number): any | undefined {
  return getDb().prepare('SELECT * FROM custom_skills WHERE id=? AND user_id=?').get(id, userId) as any;
}

skillsRouter.get('/', (req: AuthRequest, res: Response) => {
  const rows = getDb().prepare('SELECT * FROM custom_skills WHERE user_id=? ORDER BY updated_at DESC, id DESC').all(req.userId!) as any[];
  res.json(rows.map(mapSkill));
});

skillsRouter.post('/', (req: AuthRequest, res: Response) => {
  const name = String(req.body?.name || '').trim().slice(0, 120);
  if (!name) { res.status(400).json({ message: 'Skill 名称不能为空' }); return; }
  const description = String(req.body?.description || '').trim().slice(0, 1000);
  const prompt = String(req.body?.prompt_template || '').trim().slice(0, 12000);
  const triggerMode = ['manual', 'manual_or_suggest'].includes(String(req.body?.trigger_mode)) ? String(req.body.trigger_mode) : 'manual_or_suggest';
  const result = getDb().prepare(
    `INSERT INTO custom_skills (user_id, name, description, prompt_template, trigger_mode, allowed_tools, permissions)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(req.userId!, name, description, prompt, triggerMode, JSON.stringify(jsonArray(req.body?.allowed_tools)), JSON.stringify(jsonArray(req.body?.permissions)));
  res.status(201).json(mapSkill(getDb().prepare('SELECT * FROM custom_skills WHERE id=? AND user_id=?').get(Number(result.lastInsertRowid), req.userId!)));
});

skillsRouter.patch('/:id', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  const current = id ? ownSkill(req.userId!, id) : undefined;
  if (!current) { res.status(404).json({ message: 'Skill 不存在' }); return; }
  const fields: string[] = [];
  const values: Array<string | number> = [];
  if (req.body?.name !== undefined) { fields.push('name=?'); values.push(String(req.body.name || '').trim().slice(0, 120)); }
  if (req.body?.description !== undefined) { fields.push('description=?'); values.push(String(req.body.description || '').trim().slice(0, 1000)); }
  if (req.body?.prompt_template !== undefined) { fields.push('prompt_template=?'); values.push(String(req.body.prompt_template || '').trim().slice(0, 12000)); }
  if (req.body?.trigger_mode === 'manual' || req.body?.trigger_mode === 'manual_or_suggest') { fields.push('trigger_mode=?'); values.push(String(req.body.trigger_mode)); }
  if (req.body?.allowed_tools !== undefined) { fields.push('allowed_tools=?'); values.push(JSON.stringify(jsonArray(req.body.allowed_tools))); }
  if (req.body?.permissions !== undefined) { fields.push('permissions=?'); values.push(JSON.stringify(jsonArray(req.body.permissions))); }
  if (!fields.length) { res.json(mapSkill(current)); return; }
  fields.push('version=version+1');
  fields.push("updated_at=datetime('now','localtime')");
  getDb().prepare(`UPDATE custom_skills SET ${fields.join(', ')} WHERE id=? AND user_id=?`).run(...values, id!, req.userId!);
  res.json(mapSkill(ownSkill(req.userId!, id!)!));
});

skillsRouter.post('/:id/validate', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  const skill = id ? ownSkill(req.userId!, id) : undefined;
  if (!skill) { res.status(404).json({ message: 'Skill 不存在' }); return; }
  const errors: string[] = [];
  if (!String(skill.prompt_template || '').trim()) errors.push('请填写提示词模板');
  if (!parseJsonArray(skill.permissions).length) errors.push('请至少声明一项权限');
  if (errors.length) { res.json({ valid: false, errors }); return; }
  res.json({ valid: true, errors: [], note: '声明式 Skill 只允许调用已授权的系统工具' });
});

skillsRouter.post('/:id/:action', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  const action = req.params.action;
  if (!id || !['enable', 'disable'].includes(action) || !ownSkill(req.userId!, id)) { res.status(404).json({ message: 'Skill 不存在' }); return; }
  const status = action === 'enable' ? 'enabled' : 'disabled';
  getDb().prepare("UPDATE custom_skills SET status=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(status, id, req.userId!);
  res.json(mapSkill(ownSkill(req.userId!, id)!));
});


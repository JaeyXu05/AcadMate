import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { getDb } from '../db';

export const researchRouter = Router();
researchRouter.use(authMiddleware);

function projectForUser(userId: number, id: number): any | undefined {
  return getDb().prepare('SELECT * FROM research_projects WHERE id=? AND user_id=?').get(id, userId) as any;
}

function readProject(userId: number, id: number): any | undefined {
  const project = projectForUser(userId, id);
  if (!project) return undefined;
  const db = getDb();
  const conversations = db.prepare(
    `SELECT id, surface, title, status, active_goal_id, agent_thread_id, created_at, updated_at
     FROM conversations WHERE project_id=? AND user_id=? ORDER BY updated_at DESC`,
  ).all(id, userId);
  return { ...project, metadata: safeJson(project.metadata_json), conversations };
}

function safeJson(value: unknown): unknown {
  if (typeof value !== 'string' || !value.trim()) return {};
  try { return JSON.parse(value); } catch { return {}; }
}

researchRouter.get('/projects', (req: AuthRequest, res: Response) => {
  const rows = getDb().prepare(
    `SELECT p.id, p.name, p.description, p.status, p.goal, p.created_at, p.updated_at,
       (SELECT COUNT(*) FROM conversations c WHERE c.project_id=p.id AND c.user_id=p.user_id) AS conversation_count
     FROM research_projects p WHERE p.user_id=? ORDER BY p.updated_at DESC, p.id DESC`,
  ).all(req.userId!);
  res.json(rows);
});

researchRouter.post('/projects', (req: AuthRequest, res: Response) => {
  const name = String(req.body?.name || '').trim().slice(0, 200);
  if (!name) { res.status(400).json({ message: '项目名称不能为空' }); return; }
  const description = String(req.body?.description || '').trim().slice(0, 2000);
  const goal = String(req.body?.goal || '').trim().slice(0, 2000);
  const result = getDb().prepare(
    'INSERT INTO research_projects (user_id, name, description, goal) VALUES (?, ?, ?, ?)',
  ).run(req.userId!, name, description, goal);
  res.status(201).json(readProject(req.userId!, Number(result.lastInsertRowid)));
});

researchRouter.get('/projects/:id', (req: AuthRequest, res: Response) => {
  const id = Number(req.params.id);
  const project = Number.isInteger(id) ? readProject(req.userId!, id) : undefined;
  if (!project) { res.status(404).json({ message: '科研项目不存在' }); return; }
  res.json(project);
});

researchRouter.patch('/projects/:id', (req: AuthRequest, res: Response) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id) || !projectForUser(req.userId!, id)) { res.status(404).json({ message: '科研项目不存在' }); return; }
  const fields: string[] = [];
  const values: string[] = [];
  for (const key of ['name', 'description', 'goal', 'status']) {
    if (req.body?.[key] === undefined) continue;
    if (key === 'status' && !['idea', 'literature_review', 'design', 'experiment', 'analysis', 'writing', 'completed', 'archived'].includes(String(req.body[key]))) continue;
    fields.push(`${key}=?`);
    values.push(String(req.body[key] || '').trim().slice(0, key === 'name' ? 200 : 2000));
  }
  if (!fields.length) { res.json(readProject(req.userId!, id)); return; }
  fields.push("updated_at=datetime('now','localtime')");
  getDb().prepare(`UPDATE research_projects SET ${fields.join(', ')} WHERE id=? AND user_id=?`).run(...values, id, req.userId!);
  res.json(readProject(req.userId!, id));
});


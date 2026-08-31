import { Router, Response } from 'express';
import { getDb } from '../db';
import { loadGrowthState } from '../data/growthStore';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const userRouter = Router();

// 所有路由需要登录
userRouter.use(authMiddleware);

/** GET /api/user/profile — 获取用户信息 */
userRouter.get('/profile', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const user = db
    .prepare('SELECT id, email, nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(req.userId!) as Record<string, unknown> | undefined;

  if (!user) {
    res.status(404).json({ message: '用户不存在' });
    return;
  }

  res.json({
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    grade: user.grade,
    major: user.major,
    interests: safeParse(user.interests as string),
    skills: safeParse(user.skills as string),
    bio: user.bio,
  });
});

/** PUT /api/user/profile — 更新用户信息 */
userRouter.put('/profile', (req: AuthRequest, res: Response) => {
  const { nickname, grade, major, interests, skills, bio } = req.body ?? {};

  const db = getDb();

  // 只允许这些字段
  const updates: string[] = [];
  const params: unknown[] = [];

  if (nickname !== undefined) {
    updates.push('nickname = ?');
    params.push(nickname);
  }
  if (grade !== undefined) {
    updates.push('grade = ?');
    params.push(grade);
  }
  if (major !== undefined) {
    updates.push('major = ?');
    params.push(major);
  }
  if (interests !== undefined) {
    updates.push('interests = ?');
    params.push(JSON.stringify(interests));
  }
  if (skills !== undefined) {
    updates.push('skills = ?');
    params.push(JSON.stringify(skills));
  }
  if (bio !== undefined) {
    updates.push('bio = ?');
    params.push(bio);
  }

  if (updates.length > 0) {
    updates.push("updated_at = datetime('now','localtime')");
    params.push(req.userId!);
    db.prepare(`UPDATE users SET ${updates.join(', ')} WHERE id = ?`).run(...params);
  }

  // 返回更新后的用户
  const user = db
    .prepare('SELECT id, email, nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(req.userId!) as Record<string, unknown>;

  res.json({
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    grade: user.grade,
    major: user.major,
    interests: safeParse(user.interests as string),
    skills: safeParse(user.skills as string),
    bio: user.bio,
  });
});

/** DELETE /api/user/account — 注销账号（级联删除 favorites/settings/history） */
userRouter.delete('/account', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const result = db.prepare('DELETE FROM users WHERE id = ?').run(req.userId!);
  if (result.changes === 0) {
    res.status(404).json({ message: '用户不存在' });
    return;
  }
  // favorites / user_settings / search_history / chat_history / growth_state 均有 ON DELETE CASCADE，自动清理
  res.json({ deleted: true });
});

/** GET /api/user/growth — 科研成长状态 */
userRouter.get('/growth', (req: AuthRequest, res: Response) => {
  res.json(loadGrowthState(req.userId!));
});

/** PUT /api/user/growth — 成长状态只允许服务端从 Review PASS 的 AgentRun 写回。 */
userRouter.put('/growth', (_req: AuthRequest, res: Response) => {
  res.status(403).json({
    message: '科研成长状态为审核结果，只能由 Review PASS 的 AgentRun 写回',
  });
});

function safeParse(val: string): string[] {
  if (!val) return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

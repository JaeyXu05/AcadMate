import { Router, Request, Response } from 'express';
import bcrypt from 'bcryptjs';
import { getDb } from '../db';
import { generateToken } from '../middleware/auth';
import { rateLimit } from '../middleware/rateLimit';

export const authRouter = Router();

// 登录限流：同一 IP 每 5 分钟最多 20 次，防暴力猜测
authRouter.use(rateLimit({ windowMs: 5 * 60_000, max: 20, label: 'auth-login' }));

/** POST /api/auth/login — 登录（首次登录自动注册） */
authRouter.post('/login', async (req: Request, res: Response) => {
  try {
    const { email, password } = req.body ?? {};

    if (!email || !password) {
      res.status(400).json({ message: '请填写邮箱和密码' });
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      res.status(400).json({ message: '邮箱格式不正确' });
      return;
    }
    if (password.length < 6) {
      res.status(400).json({ message: '密码至少 6 位' });
      return;
    }

    const db = getDb();
    let user = db
      .prepare('SELECT id, email, password_hash, nickname, grade, major, interests, skills, bio FROM users WHERE email = ?')
      .get(email) as Record<string, unknown> | undefined;

    if (!user) {
      // 首次登录：自动注册
      const passwordHash = await bcrypt.hash(password, 10);
      const result = db
        .prepare('INSERT INTO users (email, password_hash) VALUES (?, ?)')
        .run(email, passwordHash);
      const userId = result.lastInsertRowid as number;

      db.prepare('INSERT INTO user_settings (user_id) VALUES (?)').run(userId);

      user = db
        .prepare('SELECT id, email, password_hash, nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
        .get(userId) as Record<string, unknown>;
    } else {
      // 已注册：验证密码
      const valid = await bcrypt.compare(password, user.password_hash as string);
      if (!valid) {
        res.status(401).json({ message: '密码错误' });
        return;
      }
    }

    const token = generateToken(user.id as number);

    res.json({
      token,
      user: {
        id: user.id,
        email: user.email,
        nickname: user.nickname,
        grade: user.grade,
        major: user.major,
        interests: safeParse(user.interests as string),
        skills: safeParse(user.skills as string),
        bio: user.bio,
      },
    });
  } catch (err) {
    console.error('[login] error:', err);
    res.status(500).json({ message: '登录失败，请重试' });
  }
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
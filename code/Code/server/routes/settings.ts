import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const settingsRouter = Router();

settingsRouter.use(authMiddleware);

const DEFAULTS = {
  bg_theme: 'pure-black',
  bg_color: '#000000',
  default_sort: 'match',
  card_density: 'standard',
};

/** 确保用户有设置行（懒初始化） */
function ensureSettings(userId: number): void {
  const db = getDb();
  db.prepare('INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)').run(userId);
}

/** GET /api/settings — 获取用户设置 */
settingsRouter.get('/', (req: AuthRequest, res: Response) => {
  const db = getDb();
  ensureSettings(req.userId!);

  const row = db
    .prepare('SELECT bg_theme, bg_color, default_sort, card_density FROM user_settings WHERE user_id = ?')
    .get(req.userId!) as Record<string, string> | undefined;

  res.json(row ?? DEFAULTS);
});

/** PUT /api/settings — 更新用户设置（只更新传入的字段） */
settingsRouter.put('/', (req: AuthRequest, res: Response) => {
  const { bg_theme, bg_color, default_sort, card_density } = req.body ?? {};

  const db = getDb();
  ensureSettings(req.userId!);

  // 构建动态 UPDATE，只更新非 undefined 的字段
  const setClauses: string[] = [];
  const params: unknown[] = [];

  if (bg_theme !== undefined) {
    setClauses.push('bg_theme = ?');
    params.push(bg_theme);
  }
  if (bg_color !== undefined) {
    setClauses.push('bg_color = ?');
    params.push(bg_color);
  }
  if (default_sort !== undefined) {
    setClauses.push('default_sort = ?');
    params.push(default_sort);
  }
  if (card_density !== undefined) {
    setClauses.push('card_density = ?');
    params.push(card_density);
  }

  if (setClauses.length > 0) {
    params.push(req.userId!);
    db.prepare(`UPDATE user_settings SET ${setClauses.join(', ')} WHERE user_id = ?`).run(...params);
  }

  // 返回最新设置
  const row = db
    .prepare('SELECT bg_theme, bg_color, default_sort, card_density FROM user_settings WHERE user_id = ?')
    .get(req.userId!) as Record<string, string>;

  res.json(row ?? DEFAULTS);
});
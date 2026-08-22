import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const favoritesRouter = Router();

favoritesRouter.use(authMiddleware);

/** GET /api/favorites — 获取收藏列表 */
favoritesRouter.get('/', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const rows = db
    .prepare('SELECT id, advisor_id, created_at FROM favorites WHERE user_id = ? ORDER BY created_at DESC')
    .all(req.userId!);

  res.json(rows);
});

/** POST /api/favorites — 添加收藏 */
favoritesRouter.post('/', (req: AuthRequest, res: Response) => {
  const { advisor_id } = req.body ?? {};

  if (!advisor_id) {
    res.status(400).json({ message: '缺少 advisor_id' });
    return;
  }

  const db = getDb();
  try {
    const result = db
      .prepare('INSERT OR IGNORE INTO favorites (user_id, advisor_id) VALUES (?, ?)')
      .run(req.userId!, advisor_id);

    if (result.changes === 0) {
      res.status(409).json({ message: '已收藏过该导师' });
      return;
    }

    const fav = db
      .prepare('SELECT id, advisor_id, created_at FROM favorites WHERE id = ?')
      .get(result.lastInsertRowid);

    res.status(201).json(fav);
  } catch {
    res.status(500).json({ message: '收藏失败' });
  }
});

/** DELETE /api/favorites/:advisor_id — 取消收藏 */
favoritesRouter.delete('/:advisor_id', (req: AuthRequest, res: Response) => {
  const { advisor_id } = req.params;

  const db = getDb();
  const result = db
    .prepare('DELETE FROM favorites WHERE user_id = ? AND advisor_id = ?')
    .run(req.userId!, advisor_id);

  if (result.changes === 0) {
    res.status(404).json({ message: '未找到该收藏' });
    return;
  }

  res.json({ message: '已取消收藏' });
});
import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const feedbackRouter = Router();

feedbackRouter.use(authMiddleware);

// ---- 导师负反馈（猜你喜欢「不感兴趣」）----
// dislike = 过滤排除该导师，不改变 topicOverlap 打分，也不做研究方向降权。
// like 预留（收藏 favorites 仍独立承载"进收藏夹"语义，这里仅存显式偏好信号）。
// 幂等：重复 dislike/like 不报错，直接覆盖为最新 feedback。

/** GET /api/feedback — 取当前用户的反馈列表（供前端恢复"已被不感兴趣"状态等） */
feedbackRouter.get('/', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const rows = db
    .prepare('SELECT advisor_id, feedback, created_at FROM advisor_feedback WHERE user_id = ? ORDER BY created_at DESC')
    .all(req.userId!);
  res.json(rows);
});

/** POST /api/feedback — 记录一条反馈 { advisor_id, feedback: 'like'|'dislike' } */
feedbackRouter.post('/', (req: AuthRequest, res: Response) => {
  const { advisor_id, feedback } = req.body ?? {};
  const fb = feedback === 'like' ? 'like' : 'dislike';
  if (!advisor_id) {
    res.status(400).json({ message: '缺少 advisor_id' });
    return;
  }

  const db = getDb();
  try {
    // UPSERT：单用户对单导师只保留一条最新反馈
    db.prepare(
      `INSERT INTO advisor_feedback (user_id, advisor_id, feedback)
       VALUES (?, ?, ?)
       ON CONFLICT(user_id, advisor_id)
       DO UPDATE SET feedback = excluded.feedback, created_at = datetime('now','localtime')`,
    ).run(req.userId!, advisor_id, fb);

    res.status(201).json({ advisor_id, feedback: fb });
  } catch {
    res.status(500).json({ message: '记录反馈失败' });
  }
});

/** DELETE /api/feedback/:advisor_id — 撤销反馈（重新允许该导师出现） */
feedbackRouter.delete('/:advisor_id', (req: AuthRequest, res: Response) => {
  const { advisor_id } = req.params;
  const db = getDb();
  const result = db
    .prepare('DELETE FROM advisor_feedback WHERE user_id = ? AND advisor_id = ?')
    .run(req.userId!, advisor_id);

  if (result.changes === 0) {
    res.status(404).json({ message: '未找到该反馈' });
    return;
  }
  res.json({ message: '已撤销反馈' });
});

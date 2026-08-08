import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, ragData, toAdvisorDetail } from '../data/ragAdvisors';

export const advisorsRouter = Router();

advisorsRouter.use(authMiddleware);

// ============================================================================
// 导师详情（真实 RAG 数据源）
// ----------------------------------------------------------------------------
// 由 ragAdvisors.ts 读取 C 产出的 ustc_mentor_rag.json（715 导师），用
// candidate_id（如 ustc_faculty_26275）键控，返回前端契约 AdvisorDetail。
// 检索结果（A 代理 mapFinalMentor 输出同样的 candidate_id）可直接点进详情。
// RAG 缺失时可看到明确错误，不静默返回假数据。
// ============================================================================

/** GET /api/advisors/:id — 导师详情 */
advisorsRouter.get('/:id', (req: AuthRequest, res: Response) => {
  const candidate = ragStore.getById(req.params.id);
  if (!candidate) {
    if (!ragData.isReady) {
      res.status(503).json({
        message: `导师数据源不可用：${ragData.errorMessage ?? '未知错误'}`,
      });
      return;
    }
    res.status(404).json({ message: '未找到该导师' });
    return;
  }
  res.json(toAdvisorDetail(candidate));
});

/** GET /api/advisors/:id/explanation — 推理链（详情页无动态匹配时给出 RAG 侧说明） */
advisorsRouter.get('/:id/explanation', (req: AuthRequest, res: Response) => {
  const candidate = ragStore.getById(req.params.id);
  if (!candidate) {
    if (!ragData.isReady) {
      res.status(503).json({
        message: `导师数据源不可用：${ragData.errorMessage ?? '未知错误'}`,
      });
      return;
    }
    res.status(404).json({ message: '未找到该导师' });
    return;
  }
  const detail = toAdvisorDetail(candidate);
  const reasons: string[] = [];
  if (detail.title) reasons.push(`${detail.name}，${detail.title}，${detail.department || '中科大'}。`);
  if (detail.tags.length > 0) reasons.push(`研究方向：${detail.tags.join('、')}。`);
  if (detail.recruiting) reasons.push(`招生意向：${detail.recruiting}`);
  res.json({ explanation: reasons.join('\n') || '该导师已收录于中科大导师库。' });
});
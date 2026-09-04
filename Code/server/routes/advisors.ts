import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, ragData, toAdvisorDetail } from '../data/ragAdvisors';
import { loadLatestMentorMatchArtifact } from '../data/runArtifacts';

export const advisorsRouter = Router();

advisorsRouter.use(authMiddleware);

// ============================================================================
// 导师详情（真实 RAG 数据源）
// ----------------------------------------------------------------------------
// 由 ragAdvisors.ts 读取 C 产出的 ustc_mentor_rag.json（当前 972 导师 / 1969 证据），用
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
  const detail = toAdvisorDetail(candidate);
  const artifact = loadLatestMentorMatchArtifact(req.userId!, req.params.id);
  if (artifact) {
    const matched = artifact.advisor as {
      matchScore?: number;
      explanation?: string;
      evidenceRefs?: string[];
    };
    if (typeof matched.matchScore === 'number') {
      detail.matchScore = matched.matchScore;
      detail.scoreKind = 'workflow_match';
    }
    if (matched.explanation) detail.explanation = matched.explanation;
    if (Array.isArray(matched.evidenceRefs)) {
      (detail as typeof detail & { evidenceRefs?: string[] }).evidenceRefs = matched.evidenceRefs;
    }
    (detail as typeof detail & { source_run_id?: string; source_query?: string }).source_run_id =
      String(artifact.run_id || '');
    (detail as typeof detail & { source_query?: string }).source_query =
      String(artifact.query || '');
  }
  res.json(detail);
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
  const artifact = loadLatestMentorMatchArtifact(req.userId!, req.params.id);
  const reasons: string[] = [];
  if (artifact?.query) reasons.push(`来自检索：「${String(artifact.query)}」。`);
  if (typeof (artifact?.advisor as { matchScore?: number } | undefined)?.matchScore === 'number') {
    reasons.push(`本轮匹配分 ${Number((artifact?.advisor as { matchScore?: number }).matchScore)}（导师匹配工作流 Review PASS）。`);
  }
  const evidenceRefs = (artifact?.advisor as { evidenceRefs?: string[] } | undefined)?.evidenceRefs ?? [];
  if (evidenceRefs.length) reasons.push(`证据：${evidenceRefs.slice(0, 6).join('、')}`);
  if (detail.title) reasons.push(`${detail.name}，${detail.title}，${detail.department || '中科大'}。`);
  if (detail.tags.length > 0) reasons.push(`研究方向：${detail.tags.join('、')}。`);
  if (detail.recruiting) reasons.push(`招生意向：${detail.recruiting}`);
  res.json({ explanation: reasons.join('\n') || '该导师已收录于中科大导师库。' });
});

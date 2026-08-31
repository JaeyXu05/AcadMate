import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toLightAdvisor } from '../data/ragAdvisors';
import { retrieveQualifiedMentors } from '../data/mentorRetrieval';
import { loadRecommendMemory } from '../data/userMemory';

export const recommendRouter = Router();

recommendRouter.use(authMiddleware);

recommendRouter.get('/', (req: AuthRequest, res: Response) => {
  if (!ragStore.getCandidates().length) {
    res.status(503).json({ message: '导师数据源不可用，请确认 RAG 数据已生成' });
    return;
  }

  const memory = loadRecommendMemory(req.userId!);
  const basedOn = memory.core.slice(0, 8);
  const favoriteIds = new Set(
    (getDb()
      .prepare('SELECT advisor_id FROM favorites WHERE user_id = ?')
      .all(req.userId!) as Array<{ advisor_id: string }>)
      .map((row) => row.advisor_id),
  );
  const dislikedIds = new Set(
    (getDb()
      .prepare("SELECT advisor_id FROM advisor_feedback WHERE user_id = ? AND feedback = 'dislike'")
      .all(req.userId!) as Array<{ advisor_id: string }>)
      .map((row) => row.advisor_id),
  );

  const candidatePool = ragStore.getCandidates().filter((item) => {
    if (dislikedIds.has(item.candidate_id)) return false;
    return Number(item.source_metadata?.topics_source ?? 0) === 1;
  });

  const merged = new Map<string, ReturnType<typeof retrieveQualifiedMentors>['matches'][number]>();
  for (const keyword of basedOn) {
    const retrieved = retrieveQualifiedMentors(
      keyword,
      candidatePool,
      (candidateId) => ragStore.getEvidenceFor(candidateId),
      { limit: 12, threshold: 1, personalize: true },
    );
    for (const match of retrieved.matches) {
      const current = merged.get(match.candidate.candidate_id);
      if (!current || match.finalScore > current.finalScore) merged.set(match.candidate.candidate_id, match);
    }
  }

  const ranked = [...merged.values()].filter((match) => (
    match.matchType === 'DIRECT' || match.matchType === 'ADJACENT'
  )).sort((left, right) => {
    const favoriteDelta = Number(favoriteIds.has(right.candidate.candidate_id)) - Number(favoriteIds.has(left.candidate.candidate_id));
    return favoriteDelta || right.finalScore - left.finalScore;
  });

  const result = ranked.map((match) => ({
    ...toLightAdvisor(match.candidate),
    matchScore: match.finalScore,
    scoreKind: 'calibrated_relevance_score' as const,
    matchType: match.matchType,
    scoreBreakdown: match.scoreBreakdown,
    evidence: match.evidence,
    explanation: `相对你的核心画像（${basedOn.slice(0, 3).join('、') || '近期兴趣'}）的${match.matchType === 'DIRECT' ? '直接' : '邻近'}主题重叠，不是检索页绝对阈值。`,
  }));

  res.json({
    recommendations: result,
    basedOn,
    scoreKind: 'calibrated_relevance_score',
    memory: { longTerm: memory.longTerm, recent: memory.recent },
  });
});

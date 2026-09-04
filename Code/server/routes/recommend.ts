import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toLightAdvisor } from '../data/ragAdvisors';
import { retrieveQualifiedMentors } from '../data/mentorRetrieval';
import { loadRecommendMemory } from '../data/userMemory';
import { rankRecommendations, type RecommendationSignal } from '../data/recommendRanking';

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

  const verifiedCandidates = ragStore.getCandidates().filter((item) => {
    if (dislikedIds.has(item.candidate_id)) return false;
    return Number(item.source_metadata?.topics_source ?? 0) === 1;
  });
  // "猜你喜欢" should surface discoveries, not repeat the user's collection.
  // If novelty leaves too few results we transparently fall back to favorites.
  const novelCandidates = verifiedCandidates.filter((item) => !favoriteIds.has(item.candidate_id));
  const candidatePool = novelCandidates.length >= 6 ? novelCandidates : verifiedCandidates;

  const merged = new Map<string, RecommendationSignal[]>();
  for (const [index, keyword] of basedOn.entries()) {
    const retrieved = retrieveQualifiedMentors(
      keyword,
      candidatePool,
      (candidateId) => ragStore.getEvidenceFor(candidateId),
      { limit: 12, threshold: 1, personalize: true },
    );
    for (const match of retrieved.matches) {
      const candidateId = match.candidate.candidate_id;
      const signals = merged.get(candidateId) ?? [];
      signals.push({ interest: keyword, recent: index < memory.recent.length, match });
      merged.set(candidateId, signals);
    }
  }

  const ranked = rankRecommendations(
    [...merged.entries()]
      .filter(([, signals]) => signals.some((item) => item.match.matchType === 'DIRECT' || item.match.matchType === 'ADJACENT'))
      .map(([candidateId, signals]) => ({
        candidateId,
        signals,
        profileTopicCount: signals[0].match.candidate.research_topics.length,
        publicationCount: Number(signals[0].match.candidate.source_metadata?.publication_total_count ?? signals[0].match.candidate.publications.length ?? 0),
      })),
    6,
  );

  const result = ranked.map((item) => {
    const best = item.signals.reduce((current, signal) => (
      signal.match.finalScore > current.match.finalScore ? signal : current
    ));
    return {
      ...toLightAdvisor(best.match.candidate),
      matchScore: item.score,
      scoreKind: 'personalized_recommendation' as const,
      matchType: best.match.matchType,
      scoreBreakdown: { ...best.match.scoreBreakdown, ...item.factors },
      evidence: best.match.evidence,
      matchedInterests: item.matchedInterests,
      explanation: `匹配兴趣：${item.matchedInterests.join('、')}；推荐指数综合主题相关性、兴趣覆盖、近期检索与已核验证据，不等同于检索页绝对匹配分。`,
    };
  });

  res.json({
    recommendations: result,
    basedOn,
    scoreKind: 'personalized_recommendation',
    memory: { longTerm: memory.longTerm, recent: memory.recent },
  });
});

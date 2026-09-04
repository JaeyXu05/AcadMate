import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toLightAdvisor } from '../data/ragAdvisors';
import { isTrustedTopicSource, retrieveQualifiedMentors } from '../data/mentorRetrieval';
import { loadRecommendMemory } from '../data/userMemory';
import {
  buildRecommendSignals,
  hasTrustedTopicProvenance,
  rankRecommendationMatches,
  recommendationExplanation,
  recommendationLimit,
  selectDiverseRecommendations,
} from '../data/recommendRanking';

export const recommendRouter = Router();

recommendRouter.use(authMiddleware);

recommendRouter.get('/', (req: AuthRequest, res: Response) => {
  if (!ragStore.getCandidates().length) {
    res.status(503).json({ message: '导师数据源不可用，请确认 RAG 数据已生成' });
    return;
  }

  const memory = loadRecommendMemory(req.userId!);
  const signals = buildRecommendSignals(memory);
  const basedOn = signals.map((signal) => signal.term);
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
    if (dislikedIds.has(item.candidate_id) || favoriteIds.has(item.candidate_id)) return false;
    if (!isTrustedTopicSource(item.source_metadata?.topics_source)) return false;
    return hasTrustedTopicProvenance(item, ragStore.getEvidenceFor(item.candidate_id));
  });

  const signalMatches = [];
  for (const signal of signals) {
    const retrieved = retrieveQualifiedMentors(
      signal.term,
      candidatePool,
      (candidateId) => ragStore.getEvidenceFor(candidateId),
      { limit: 12, threshold: 1, personalize: true },
    );
    signalMatches.push({ signal, matches: retrieved.matches });
  }

  const ranked = rankRecommendationMatches(signalMatches, signals).filter((item) => (
    item.match.matchType === 'DIRECT' || item.match.matchType === 'ADJACENT'
  ));
  const selected = selectDiverseRecommendations(ranked, recommendationLimit());

  const result = selected.map((item) => ({
    ...toLightAdvisor(item.match.candidate),
    matchScore: item.match.finalScore,
    scoreKind: 'calibrated_relevance_score' as const,
    matchType: item.match.matchType,
    scoreBreakdown: {
      ...item.match.scoreBreakdown,
      profile_coverage: item.profileCoverage,
      evidence_quality: item.evidenceQuality,
      publication_support: item.publicationSupport,
    },
    evidence: item.evidence,
    explanation: recommendationExplanation(item),
  }));

  res.json({
    recommendations: result,
    basedOn,
    scoreKind: 'calibrated_relevance_score',
    needsOnboarding: signals.length === 0,
    memory: { longTerm: memory.longTerm, recent: memory.recent, favorite: memory.favorite },
  });
});

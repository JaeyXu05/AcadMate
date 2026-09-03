import type { MentorMatch } from './mentorRetrieval';

export interface RecommendationSignal {
  interest: string;
  recent: boolean;
  match: MentorMatch;
}

export interface RecommendationCandidate {
  candidateId: string;
  signals: RecommendationSignal[];
  profileTopicCount: number;
  publicationCount: number;
}

export interface RankedRecommendation extends RecommendationCandidate {
  score: number;
  matchedInterests: string[];
  factors: {
    bestSemantic: number;
    interestCoverage: number;
    recentInterest: number;
    evidenceStrength: number;
    profileCompleteness: number;
  };
}

/**
 * Recommendation scores are intentionally not search-page relevance scores.
 * Every input signal has already passed the semantic/evidence gate; this
 * function ranks those qualified candidates using the user's whole profile.
 */
export function rankRecommendations(
  candidates: RecommendationCandidate[],
  limit = 6,
): RankedRecommendation[] {
  const preliminary = candidates.map((candidate) => {
    const bestSemantic = Math.max(...candidate.signals.map((item) => item.match.finalScore));
    const matchedInterests = [...new Set(candidate.signals.map((item) => item.interest))];
    const directCount = candidate.signals.filter((item) => item.match.matchType === 'DIRECT').length;
    const evidenceCount = candidate.signals.reduce(
      (total, item) => total + item.match.evidence.filter((evidence) => evidence.support_type !== 'IDENTITY').length,
      0,
    );
    const interestCoverage = Math.min(8, Math.max(0, matchedInterests.length - 1) * 4);
    const recentInterest = candidate.signals.some((item) => item.recent) ? 2.5 : 0;
    const evidenceStrength = Math.min(3, evidenceCount * 0.9 + Math.max(0, directCount - 1) * 0.4);
    const profileCompleteness = Math.min(
      1.5,
      Math.log2(1 + Math.max(0, candidate.profileTopicCount)) * 0.45
        + Math.log2(1 + Math.max(0, candidate.publicationCount)) * 0.12,
    );
    // 65 is the qualified-candidate floor; semantic relevance remains the
    // largest component, while profile-wide coverage breaks 92-point ties.
    const rawScore = Math.min(
      99,
      65 + bestSemantic * 0.25 + interestCoverage + recentInterest + evidenceStrength + profileCompleteness,
    );
    return {
      ...candidate,
      matchedInterests,
      score: round(rawScore),
      factors: {
        bestSemantic: round(bestSemantic),
        interestCoverage: round(interestCoverage),
        recentInterest: round(recentInterest),
        evidenceStrength: round(evidenceStrength),
        profileCompleteness: round(profileCompleteness),
      },
    };
  });

  preliminary.sort((left, right) => (
    right.score - left.score
    || right.factors.bestSemantic - left.factors.bestSemantic
    || right.matchedInterests.length - left.matchedInterests.length
    || left.candidateId.localeCompare(right.candidateId)
  ));

  // This is a relative recommendation index.  A small monotonic display gap
  // prevents a row of indistinguishable 92s while never changing rank.
  let previous = 100.2;
  return preliminary.slice(0, limit).map((item) => {
    const score = round(Math.min(item.score, previous - 1.2));
    previous = score;
    return { ...item, score };
  });
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}

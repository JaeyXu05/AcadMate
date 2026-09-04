import type { BoundEvidence, MentorMatch } from './mentorRetrieval';
import { isTrustedTopicSource } from './mentorRetrieval';
import type { RagEvidence, RagMentor } from './ragAdvisors';

export type RecommendSignalSource = 'recent' | 'longTerm' | 'favorite';

export interface RecommendSignal {
  term: string;
  source: RecommendSignalSource;
  weight: number;
}

export interface RecommendMemoryInput {
  longTerm: string[];
  recent: string[];
  favorite: string[];
}

export interface RankedRecommendation {
  match: MentorMatch;
  /** Personalized display score; the underlying match remains the absolute score. */
  recommendationScore: number;
  recommendationBreakdown: Record<string, number>;
  signals: RecommendSignal[];
  matchedTerms: string[];
  evidence: BoundEvidence[];
  profileCoverage: number;
  evidenceQuality: number;
  publicationSupport: number;
}

const SIGNAL_WEIGHT: Record<RecommendSignalSource, number> = {
  recent: 1.2,
  longTerm: 1,
  favorite: 0.6,
};

function normalizedKey(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

export function buildRecommendSignals(memory: RecommendMemoryInput): RecommendSignal[] {
  const selected = new Map<string, RecommendSignal>();
  const append = (terms: string[], source: RecommendSignalSource) => {
    for (const raw of terms) {
      const term = String(raw || '').trim();
      if (!term) continue;
      const key = normalizedKey(term);
      const signal = { term, source, weight: SIGNAL_WEIGHT[source] };
      const current = selected.get(key);
      if (!current || signal.weight > current.weight) selected.set(key, signal);
    }
  };
  // 同一方向同时出现在多处时，以近期检索的较高权重为准。
  append(memory.recent.slice(0, 2), 'recent');
  append(memory.longTerm.slice(0, 4), 'longTerm');
  append(memory.favorite.slice(0, 2), 'favorite');
  return [...selected.values()].slice(0, 8);
}

/** source=3 必须能回溯到已核验平台论文和独立的论文方向推断证据。 */
export function hasTrustedTopicProvenance(candidate: RagMentor, evidence: RagEvidence[]): boolean {
  const source = Number(candidate.source_metadata?.topics_source ?? 0);
  if (!isTrustedTopicSource(source)) return false;
  if (source === 1) return true;
  const platforms = String(candidate.source_metadata?.paper_platforms ?? '').trim();
  const platformEvidence = evidence.some((item) => (
    /openalex|s2|dblp/.test(String(item.source_type ?? '').toLowerCase())
    && item.metadata?.identity_verified === true
    && String(item.metadata?.supports_fields ?? '').split(',').some((field) => field.trim() === 'publications')
  ));
  const inferenceEvidence = evidence.some((item) => (
    item.source_type === 'verified_paper_topic_inference'
    && item.metadata?.identity_verified === true
    && String(item.metadata?.supports_fields ?? '').split(',').some((field) => field.trim() === 'research_topics')
  ));
  return candidate.source_metadata?.paper_identity_verified === true
    && Boolean(platforms)
    && platformEvidence
    && inferenceEvidence;
}

function evidenceItemQuality(item: BoundEvidence): number {
  const sourceLevel = ({ L1: 100, L2: 90, L3: 82, L4: 55, L5: 35 } as Record<string, number>)[item.source_level] ?? 45;
  const freshness = ({ current: 100, recent: 85, unknown: 60, stale: 35 } as Record<string, number>)[item.freshness] ?? 60;
  const confidence = Math.max(0, Math.min(100, Number(item.confidence || 0) * 100));
  const relevance = Math.max(0, Math.min(100, Number(item.query_relevance || 0) * 100));
  return 0.4 * confidence + 0.3 * relevance + 0.2 * sourceLevel + 0.1 * freshness;
}

function evidenceQuality(items: BoundEvidence[]): number {
  const deduped = new Map<string, BoundEvidence>();
  for (const item of items) {
    const key = item.evidence_id || `${item.source_type}:${item.source_uri}:${item.title}`;
    const current = deduped.get(key);
    if (!current || evidenceItemQuality(item) > evidenceItemQuality(current)) deduped.set(key, item);
  }
  const scores = [...deduped.values()]
    .filter((item) => item.support_type !== 'IDENTITY')
    .map(evidenceItemQuality)
    .sort((a, b) => b - a)
    .slice(0, 3);
  if (!scores.length) return 0;
  const sourceKinds = new Set([...deduped.values()].map((item) => item.source_type).filter(Boolean)).size;
  const diversityBonus = Math.min(6, Math.max(0, sourceKinds - 1) * 2);
  return Math.round(Math.min(100, scores.reduce((sum, score) => sum + score, 0) / scores.length + diversityBonus));
}

function publicationSupport(candidate: RagMentor): number {
  if (candidate.source_metadata?.paper_identity_verified !== true) return 0;
  const count = Array.isArray(candidate.publications) ? candidate.publications.length : 0;
  if (!count) return 0;
  return Math.round(Math.min(100, (Math.log2(count + 1) / Math.log2(21)) * 100));
}

function betterMatch(left: MentorMatch, right: MentorMatch): MentorMatch {
  if (right.finalScore !== left.finalScore) return right.finalScore > left.finalScore ? right : left;
  if (right.matchType !== left.matchType) return right.matchType === 'DIRECT' ? right : left;
  return right.candidate.candidate_id.localeCompare(left.candidate.candidate_id) < 0 ? right : left;
}

export function rankRecommendationMatches(
  signalMatches: Array<{ signal: RecommendSignal; matches: MentorMatch[] }>,
  allSignals: RecommendSignal[],
): RankedRecommendation[] {
  const merged = new Map<string, {
    match: MentorMatch;
    signals: Map<string, RecommendSignal>;
    terms: Set<string>;
    evidence: Map<string, BoundEvidence>;
  }>();

  for (const { signal, matches } of signalMatches) {
    for (const match of matches) {
      const id = match.candidate.candidate_id;
      const current = merged.get(id) ?? {
        match,
        signals: new Map<string, RecommendSignal>(),
        terms: new Set<string>(),
        evidence: new Map<string, BoundEvidence>(),
      };
      current.match = betterMatch(current.match, match);
      current.signals.set(normalizedKey(signal.term), signal);
      for (const term of match.matchedTerms) current.terms.add(term);
      for (const item of match.evidence) current.evidence.set(item.evidence_id, item);
      merged.set(id, current);
    }
  }

  const totalWeight = Math.max(1, allSignals.reduce((sum, signal) => sum + signal.weight, 0));
  const ranked = [...merged.values()].map((item): RankedRecommendation => {
    const signals = [...item.signals.values()];
    const coverage = 100 * signals.reduce((sum, signal) => sum + signal.weight, 0) / totalWeight;
    const evidence = [...item.evidence.values()];
    const profileCoverage = Math.round(coverage);
    const quality = evidenceQuality(evidence);
    const publication = publicationSupport(item.match.candidate);
    // Keep A/D's calibrated relevance as the largest component, then blend in
    // only auditable recommendation signals.  A weighted blend (rather than
    // an additive score with a hard cap) preserves visible differences among
    // high-scoring direct matches without pushing every row to 99/100.
    const recommendationScore = round(
      item.match.finalScore * 0.8
        + profileCoverage * 0.12
        + quality * 0.05
        + publication * 0.03,
      1,
    );
    return {
      match: item.match,
      signals,
      matchedTerms: [...item.terms],
      evidence,
      profileCoverage,
      evidenceQuality: quality,
      publicationSupport: publication,
      recommendationScore,
      recommendationBreakdown: {
        recommendation_base_score: round(item.match.finalScore),
        recommendation_profile_coverage: profileCoverage,
        recommendation_evidence_quality: quality,
        recommendation_publication_support: publication,
        recommendation_score: recommendationScore,
      },
    };
  });

  return ranked.sort((left, right) => {
    const typeDelta = Number(right.match.matchType === 'DIRECT') - Number(left.match.matchType === 'DIRECT');
    return typeDelta
      || right.recommendationScore - left.recommendationScore
      || right.match.finalScore - left.match.finalScore
      || right.profileCoverage - left.profileCoverage
      || right.evidenceQuality - left.evidenceQuality
      || right.publicationSupport - left.publicationSupport
      || left.match.candidate.candidate_id.localeCompare(right.match.candidate.candidate_id);
  });
}

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export function recommendationLimit(raw = process.env.RECOMMEND_LIMIT): number {
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? Math.min(12, Math.max(1, Math.floor(parsed))) : 6;
}

export function selectDiverseRecommendations(
  ranked: RankedRecommendation[],
  limit = recommendationLimit(),
): RankedRecommendation[] {
  const selected: RankedRecommendation[] = [];
  const deferred: RankedRecommendation[] = [];
  const departments = new Map<string, number>();
  for (const item of ranked) {
    const department = String(item.match.candidate.department || '未知院系');
    if ((departments.get(department) ?? 0) >= 2) {
      deferred.push(item);
      continue;
    }
    selected.push(item);
    departments.set(department, (departments.get(department) ?? 0) + 1);
    if (selected.length >= limit) return selected;
  }
  for (const item of deferred) {
    selected.push(item);
    if (selected.length >= limit) break;
  }
  return selected;
}

export function recommendationExplanation(item: RankedRecommendation): string {
  const labels: Record<RecommendSignalSource, string> = {
    recent: '最近关注',
    longTerm: '长期方向',
    favorite: '收藏偏好',
  };
  const signalText = item.signals
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3)
    .map((signal) => `${labels[signal.source]}“${signal.term}”`)
    .join('、');
  const relation = item.match.matchType === 'DIRECT' ? '直接相关' : '方向邻近';
  const term = item.matchedTerms[0];
  const strongest = item.evidence
    .filter((evidence) => evidence.support_type !== 'IDENTITY')
    .sort((a, b) => evidenceItemQuality(b) - evidenceItemQuality(a))[0];
  const support = term
    ? `匹配主题“${term}”`
    : strongest?.title
      ? `由“${strongest.title}”提供研究方向证据`
      : '已有核验研究方向证据';
  return `与${signalText || '你的研究画像'}${relation}；${support}。`;
}

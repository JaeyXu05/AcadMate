import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildRecommendSignals,
  hasTrustedTopicProvenance,
  rankRecommendationMatches,
  recommendationExplanation,
  recommendationLimit,
  selectDiverseRecommendations,
  type RecommendSignal,
} from './recommendRanking';
import type { BoundEvidence, MentorMatch } from './mentorRetrieval';
import type { RagEvidence, RagMentor } from './ragAdvisors';

function candidate(id: string, department = '计算机学院', papers = 0): RagMentor {
  return {
    candidate_id: id,
    mentor_name: id,
    department,
    research_topics: ['大模型'],
    publications: Array.from({ length: papers }, (_, index) => `paper-${index}`),
    source_metadata: { topics_source: 1, paper_identity_verified: papers > 0 },
  };
}

function bound(id: string, quality: 'high' | 'low' = 'high'): BoundEvidence {
  return {
    evidence_id: `${id}:profile`, candidate_id: id,
    source_type: quality === 'high' ? 'ustc_official_faculty_profile' : 'other',
    source_uri: `https://example.com/${id}`, title: `${id} profile`, extracted_fact: '研究大模型',
    freshness: quality === 'high' ? 'current' : 'unknown', confidence: quality === 'high' ? 0.98 : 0.55,
    source_level: quality === 'high' ? 'L1' : 'L5', support_type: 'DIRECT',
    query_relevance: quality === 'high' ? 1 : 0.7, entity_verified: true, query: '大模型',
  };
}

function match(id: string, options: {
  score?: number; type?: 'DIRECT' | 'ADJACENT'; department?: string; papers?: number;
  terms?: string[]; quality?: 'high' | 'low';
} = {}): MentorMatch {
  const score = options.score ?? 92;
  const type = options.type ?? 'DIRECT';
  return {
    candidate: candidate(id, options.department, options.papers),
    finalScore: score,
    matchType: type,
    scoreBreakdown: { topic_match: score },
    evidence: [bound(id, options.quality)],
    matchedTerms: options.terms ?? ['大模型'],
    fallback: false,
  };
}

const recent: RecommendSignal = { term: '大模型', source: 'recent', weight: 1.2 };
const longTerm: RecommendSignal = { term: '自然语言处理', source: 'longTerm', weight: 1 };

test('signals reserve recent, long-term and favorite quotas and deduplicate by strongest source', () => {
  const signals = buildRecommendSignals({
    recent: ['大模型', '机器人'],
    longTerm: ['大模型', '推荐系统', '视觉', '量子', '光学'],
    favorite: ['碳材料', '催化', '蛋白质结构'],
  });
  assert.equal(signals.length, 7);
  assert.deepEqual(signals.filter((item) => item.source === 'recent').map((item) => item.term), ['大模型', '机器人']);
  assert.equal(signals.find((item) => item.term === '大模型')?.weight, 1.2);
  assert.deepEqual(signals.filter((item) => item.source === 'favorite').map((item) => item.term), ['碳材料', '催化']);
});

test('source 3 requires verified platform and inference provenance', () => {
  const mentor: RagMentor = {
    ...candidate('paper-topic'),
    source_metadata: {
      topics_source: 3,
      paper_identity_verified: true,
      paper_platforms: 's2',
    },
  };
  const valid: RagEvidence[] = [
    {
      evidence_id: 'platform', candidate_id: mentor.candidate_id, source_type: 's2_paper_metadata',
      metadata: { identity_verified: true, supports_fields: 'research_topics,methods,publications' },
    },
    {
      evidence_id: 'inference', candidate_id: mentor.candidate_id, source_type: 'verified_paper_topic_inference',
      metadata: { identity_verified: true, supports_fields: 'research_topics' },
    },
  ];
  assert.equal(hasTrustedTopicProvenance(mentor, valid), true);
  assert.equal(hasTrustedTopicProvenance(mentor, valid.slice(0, 1)), false);
  assert.equal(hasTrustedTopicProvenance({ ...mentor, source_metadata: { topics_source: 2 } }, valid), false);
});

test('profile coverage and evidence quality break equal relevance ties before candidate id', () => {
  const ranked = rankRecommendationMatches([
    { signal: recent, matches: [match('z-single'), match('a-weak', { quality: 'low' })] },
    { signal: longTerm, matches: [match('z-single')] },
  ], [recent, longTerm]);
  assert.equal(ranked[0].match.candidate.candidate_id, 'z-single');
  assert.equal(ranked[0].profileCoverage, 100);
  assert.ok(ranked[0].evidenceQuality > ranked[1].evidenceQuality);
});

test('DIRECT always remains ahead of ADJACENT regardless of auxiliary quality', () => {
  const ranked = rankRecommendationMatches([
    { signal: recent, matches: [
      match('direct', { score: 70, type: 'DIRECT', quality: 'low' }),
      match('adjacent', { score: 99, type: 'ADJACENT', quality: 'high', papers: 20 }),
    ] },
  ], [recent]);
  assert.equal(ranked[0].match.candidate.candidate_id, 'direct');
});

test('diversity caps a department at two before filling remaining slots', () => {
  const matches = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((id, index) => (
    match(id, { department: index < 4 ? '计算机学院' : `学院-${index}` })
  ));
  const ranked = rankRecommendationMatches([{ signal: recent, matches }], [recent]);
  const selected = selectDiverseRecommendations(ranked, 6);
  assert.equal(selected.length, 6);
  assert.equal(selected.slice(0, 5).filter((item) => item.match.candidate.department === '计算机学院').length, 2);
});

test('limit defaults to six and is clamped to one through twelve', () => {
  assert.equal(recommendationLimit(undefined), 6);
  assert.equal(recommendationLimit('0'), 1);
  assert.equal(recommendationLimit('99'), 12);
});

test('mentor explanation mentions only signals that matched that mentor', () => {
  const ranked = rankRecommendationMatches([
    { signal: recent, matches: [match('mentor')] },
    { signal: longTerm, matches: [] },
  ], [recent, longTerm]);
  const explanation = recommendationExplanation(ranked[0]);
  assert.match(explanation, /大模型/);
  assert.doesNotMatch(explanation, /自然语言处理/);
});

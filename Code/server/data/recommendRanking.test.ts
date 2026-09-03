import test from 'node:test';
import assert from 'node:assert/strict';
import { rankRecommendations } from './recommendRanking';
import type { MentorMatch } from './mentorRetrieval';

function match(score: number, type: 'DIRECT' | 'ADJACENT' = 'DIRECT'): MentorMatch {
  return {
    candidate: { candidate_id: `mentor-${score}`, mentor_name: '测试导师', research_topics: [], methods: [], publications: [], evidence_refs: [], source_metadata: {} },
    finalScore: score,
    matchType: type,
    scoreBreakdown: {},
    evidence: [{ evidence_id: 'profile', candidate_id: 'test', source_type: 'official_faculty_profile', source_uri: '', title: '', extracted_fact: '', freshness: 'unknown', confidence: 1, source_level: 'L1', support_type: type, query_relevance: 1, entity_verified: true, query: '测试' }],
    matchedTerms: ['测试'],
    fallback: false,
  };
}

test('recommendation ranking rewards multi-interest coverage and spreads display scores', () => {
  const ranked = rankRecommendations([
    { candidateId: 'single', signals: [{ interest: '量子信息', recent: false, match: match(92) }], profileTopicCount: 1, publicationCount: 0 },
    { candidateId: 'multi', signals: [{ interest: '量子信息', recent: true, match: match(92) }, { interest: '量子光学', recent: false, match: match(92) }], profileTopicCount: 4, publicationCount: 8 },
    { candidateId: 'same-score', signals: [{ interest: '量子信息', recent: false, match: match(92) }], profileTopicCount: 1, publicationCount: 0 },
  ]);

  assert.equal(ranked[0].candidateId, 'multi');
  assert.deepEqual(ranked[0].matchedInterests, ['量子信息', '量子光学']);
  assert.ok(ranked[0].score - ranked[1].score >= 1.2);
  assert.ok(ranked[1].score - ranked[2].score >= 1.2);
});

test('recommendation ranking remains bounded and never changes semantic eligibility', () => {
  const ranked = rankRecommendations([
    { candidateId: 'only', signals: [{ interest: '大语言模型', recent: false, match: match(76, 'ADJACENT') }], profileTopicCount: 0, publicationCount: 0 },
  ]);
  assert.equal(ranked.length, 1);
  assert.ok(ranked[0].score >= 65 && ranked[0].score <= 99);
  assert.equal(ranked[0].signals[0].match.matchType, 'ADJACENT');
});

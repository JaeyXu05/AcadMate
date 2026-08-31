import test from 'node:test';
import assert from 'node:assert/strict';
import { buildQueryContract, keepDisplayableAdvisors, longTermInterestTerms, retrieveQualifiedMentors, reviewMatches } from './mentorRetrieval';
import { ragStore } from './ragAdvisors';
import type { RagEvidence, RagMentor } from './ragAdvisors';

function mentor(id: string, topics: string[], topicsSource = 1): RagMentor {
  return {
    candidate_id: id,
    mentor_name: id,
    research_topics: topics,
    methods: [],
    publications: [],
    evidence_refs: [`${id}:identity`, `${id}:profile`],
    source_metadata: { topics_source: topicsSource },
  };
}

function evidence(id: string): RagEvidence[] {
  return [
    {
      evidence_id: `${id}:identity`, candidate_id: id,
      source_type: 'ustc_official_faculty_directory', source_uri: 'https://ustc.example/directory',
      metadata: { identity_verified: true, supports_fields: 'affiliation,department' },
    },
    {
      evidence_id: `${id}:profile`, candidate_id: id,
      source_type: 'ustc_official_faculty_profile', source_uri: `https://ustc.example/${id}`,
      metadata: { identity_verified: true, supports_fields: 'research_topics' },
    },
  ];
}

test('query contract preserves recommendation and generative qualifiers', () => {
  assert.equal(buildQueryContract('推荐系统').canonicalQuery, '推荐系统');
  assert.deepEqual(buildQueryContract('推荐系统').mustPreserve, ['推荐']);
  assert.deepEqual(buildQueryContract('生成式人工智能').mustPreserve, ['生成式']);
});

test('natural-language wrapper does not become part of the canonical topic', () => {
  const contract = buildQueryContract('请帮我找生成式人工智能方向的导师');
  assert.equal(contract.canonicalQuery, '生成式人工智能');
  assert.deepEqual(contract.mustPreserve, ['生成式']);
});

test('narrow queries reject parent-only and unrelated candidates without filling top-k', () => {
  const candidates = [
    mentor('generic-ai', ['人工智能', '机器学习']),
    mentor('generative', ['大语言模型', '扩散模型']),
    mentor('hydrogen', ['氢能与燃料电池']),
  ];
  const result = retrieveQualifiedMentors(
    '生成式人工智能', candidates, (id) => evidence(id), { limit: 5 },
  );
  assert.deepEqual(result.matches.map((item) => item.candidate.candidate_id), ['generative']);
  assert.ok(result.matches[0].finalScore >= 60);
  assert.equal(result.matches[0].evidence.every((item) => item.candidate_id === 'generative'), true);
});

test('fallback keeps the query and lowers confidence instead of changing candidates', () => {
  const candidates = [mentor('recsys', ['推荐系统'])];
  const primary = retrieveQualifiedMentors('推荐系统', candidates, (id) => evidence(id));
  const fallback = retrieveQualifiedMentors('推荐系统', candidates, (id) => evidence(id), { fallback: true });
  assert.equal(primary.matches[0].candidate.candidate_id, fallback.matches[0].candidate.candidate_id);
  assert.ok(fallback.matches[0].finalScore < primary.matches[0].finalScore);
});

test('paper-inferred topics cannot become facts or qualify a mentor', () => {
  const result = retrieveQualifiedMentors(
    '推荐系统', [mentor('inferred', ['推荐系统'], 2)], (id) => evidence(id),
  );
  assert.equal(result.matches.length, 0);
});

test('generic AI parent and application-only profiles do not fill top-k', () => {
  const result = retrieveQualifiedMentors(
    '生成式人工智能',
    [
      mentor('parent', ['人工智能', '机器学习']),
      mentor('quake', ['人工智能', '地震预测']),
      mentor('hydrogen', ['氢能与燃料电池', '海洋工程']),
      mentor('gen', ['大语言模型']),
    ],
    (id) => evidence(id),
    { limit: 5 },
  );
  assert.deepEqual(result.matches.map((item) => item.candidate.candidate_id), ['gen']);
  assert.equal(result.matches.length < 5, true);
});

test('evidence is bound per mentor and expansion terms are not evidence', () => {
  const result = retrieveQualifiedMentors(
    '生成式人工智能',
    [mentor('gen', ['大语言模型'])],
    (id) => evidence(id),
  );
  assert.equal(result.matches.length, 1);
  assert.ok(result.matches[0].evidence.every((item) => item.candidate_id === 'gen'));
  assert.equal(result.matches[0].evidence.some((item) => item.title === 'generative ai'), false);
  assert.ok(result.matches[0].evidence.every((item) => item.freshness !== 'recent' && item.freshness !== 'current'));
});

test('review reports no-match instead of approving an empty padded list', () => {
  const result = retrieveQualifiedMentors(
    '生成式人工智能',
    [mentor('hydrogen', ['氢能与燃料电池'])],
    (id) => evidence(id),
  );
  const review = reviewMatches(result.query, result.matches);
  assert.equal(result.matches.length, 0);
  assert.equal(review.status, 'NO_MATCH');
  assert.ok(review.failed_checks.includes('no_qualified_match'));
});

test('score 14 and zero shared topics never enter the result array', () => {
  const candidates = [
    mentor('zhangjie-softmatter', ['软物质仿生动力学', '活性物质', '光学显微成像', '计算机视觉辅助图像处理']),
    mentor('generic-ai', ['人工智能', '机器学习']),
  ];
  const result = retrieveQualifiedMentors(
    '生成式人工智能',
    candidates,
    (id) => evidence(id),
    { limit: 5, threshold: 60 },
  );
  assert.equal(result.matches.length, 0);
  assert.equal(result.matches.some((item) => item.finalScore < 60), false);
  const leaked = keepDisplayableAdvisors([
    { matchScore: 29, matchType: 'UNASSESSED', scoreBreakdown: { topic_match: 29 } },
    { matchScore: 14, matchType: 'UNASSESSED', scoreBreakdown: { topic_match: 0 } },
    { matchScore: 14, matchType: 'DIRECT', scoreBreakdown: { topic_match: 14 } },
  ]);
  assert.deepEqual(leaked, []);
});

test('real RAG 张洁 is not a qualified hit for 生成式人工智能', () => {
  const pool = ragStore.getCandidates();
  assert.ok(pool.length > 0, 'RAG 导师库应可加载');
  const zhangJie = pool.filter((item) => item.mentor_name === '张洁');
  assert.ok(zhangJie.length > 0, '真实库里应有张洁');
  const result = retrieveQualifiedMentors(
    '生成式人工智能',
    pool,
    (id) => ragStore.getEvidenceFor(id),
    { limit: 5, threshold: 60 },
  );
  assert.equal(result.matches.some((item) => item.candidate.mentor_name === '张洁'), false);
  assert.equal(result.matches.every((item) => item.finalScore >= 60), true);
  assert.equal(
    keepDisplayableAdvisors(result.matches.map((item) => ({
      matchScore: item.finalScore,
      matchType: item.matchType,
      scoreBreakdown: item.scoreBreakdown,
    }))).length,
    result.matches.length,
  );
});

test('long-term interest memory keeps canonical query and drops expansion parents', () => {
  const terms = longTermInterestTerms([
    '推荐系统',
    '人工智能',
    '机器学习',
    '请帮我找生成式人工智能方向的导师',
    'deep learning',
  ]);
  assert.ok(terms.includes('推荐系统'));
  assert.ok(terms.includes('生成式人工智能'));
  assert.equal(terms.some((item) => item === '人工智能' || item === '机器学习' || item === 'deep learning'), false);
});

test('personalized retrieval does not remap adjacent matches below search-page 60', () => {
  const candidates = [mentor('recsys', ['推荐系统', '协同过滤'])];
  const search = retrieveQualifiedMentors('推荐系统', candidates, (id) => evidence(id), { threshold: 60 });
  const personalized = retrieveQualifiedMentors(
    '推荐系统',
    candidates,
    (id) => evidence(id),
    { threshold: 1, personalize: true },
  );
  assert.ok(search.matches.length >= 1);
  assert.ok(personalized.matches.length >= 1);
  assert.equal(personalized.matches[0].matchType === 'DIRECT' || personalized.matches[0].matchType === 'ADJACENT', true);
});


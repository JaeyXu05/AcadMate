import type { RagEvidence, RagMentor } from './ragAdvisors';

export interface QueryContract {
  rawQuery: string;
  canonicalQuery: string;
  mustPreserve: string[];
  expandedTerms: string[];
  excludedGeneralizations: string[];
  semanticBoundary?: string;
  /** V2 typed concepts are forwarded by A and kept for audit/UI consumers. */
  concepts?: Array<{
    concept_id?: string;
    surface?: string;
    canonical?: string;
    role?: string;
    required?: boolean;
    must_preserve?: string[];
    confidence?: number;
    source?: string;
  }>;
  logic?: 'AND' | 'OR' | string;
  version?: number;
}

export interface BoundEvidence {
  evidence_id: string;
  candidate_id: string;
  source_type: string;
  source_uri: string;
  title: string;
  extracted_fact: string;
  locator?: string;
  retrieved_at?: string;
  freshness: string;
  confidence: number;
  source_level: string;
  support_type: 'DIRECT' | 'ADJACENT' | 'IDENTITY';
  query_relevance: number;
  entity_verified: boolean;
  query: string;
}

export interface MentorMatch {
  candidate: RagMentor;
  finalScore: number;
  matchType: 'DIRECT' | 'ADJACENT';
  scoreBreakdown: Record<string, number>;
  evidence: BoundEvidence[];
  matchedTerms: string[];
  fallback: boolean;
}

export interface ReviewOutcome {
  status: 'PASS' | 'NO_MATCH' | 'VETO';
  failed_checks: string[];
  reviewer_summary: string;
  no_match: boolean;
}

interface Boundary {
  name: string;
  triggers: string[];
  preserve: string[];
  expansions: string[];
  parents: string[];
}

const BOUNDARIES: Boundary[] = [
  {
    name: 'generative_ai',
    triggers: ['生成式人工智能', '生成式ai', 'generative ai', '生成模型', '大语言模型', '大模型', 'llm', '扩散模型', 'diffusion model', 'foundation model'],
    preserve: ['生成式'],
    expansions: ['generative ai', '生成模型', '大语言模型', 'llm', '扩散模型', 'diffusion model', '基础模型', 'foundation model'],
    parents: ['人工智能', 'ai', '机器学习', 'machine learning', '深度学习', '多模态'],
  },
  {
    name: 'recommender_systems',
    triggers: ['推荐系统', '推荐算法', 'recommender system', 'recommendation system', '协同过滤', 'collaborative filtering', 'ctr预估', '点击率预估'],
    preserve: ['推荐'],
    expansions: ['recommender system', 'recommendation system', '推荐算法', '协同过滤', 'collaborative filtering', '排序学习', 'learning to rank', 'ctr预估'],
    parents: ['人工智能', 'ai', '机器学习', '数据科学', '大数据'],
  },
  {
    name: 'multimodal_generation',
    triggers: ['多模态生成', 'multimodal generation', '文生图', 'text-to-image', '视觉语言生成'],
    preserve: ['多模态', '生成'],
    expansions: ['multimodal generation', '文生图', 'text-to-image', '视觉语言生成', '扩散模型'],
    parents: ['多模态', 'multimodal', '人工智能', '机器学习'],
  },
];

const GENERIC_PARENTS = [
  '人工智能', 'ai', 'artificial intelligence', '机器学习', 'machine learning',
  '深度学习', 'deep learning', '数据科学', 'data science', '计算机科学', 'computer science',
];

const APPLICATION_HINTS = [
  '地震', 'earthquake', 'seismic', '氢能', 'hydrogen', '燃料电池', 'fuel cell',
  '海洋', 'ocean', 'marine', '遥感', 'remote sensing', '医学影像', 'medical imaging',
  '金融', 'finance', '生物信息', 'bioinformatics', '气候', 'climate', '催化', 'catalysis',
  '光伏', 'photovoltaic', '储能', 'energy storage',
];

export function relevanceThreshold(): number {
  const raw = Number(process.env.MENTOR_RELEVANCE_THRESHOLD);
  return Number.isFinite(raw) && raw > 0 ? raw : 60;
}

/** SSE / 推荐页写出前的最后一关：低分、未评估、0 主题重叠不得进入结果数组。 */
export function keepDisplayableAdvisors<T extends {
  matchScore?: number;
  matchType?: string;
  scoreBreakdown?: Record<string, number>;
}>(advisors: T[], threshold = relevanceThreshold()): T[] {
  return advisors.filter((advisor) => {
    const score = Number(advisor.matchScore);
    if (!Number.isFinite(score) || score < threshold) return false;
    if (advisor.matchType !== 'DIRECT' && advisor.matchType !== 'ADJACENT') return false;
    const topic = Number(advisor.scoreBreakdown?.topic_match);
    if (Number.isFinite(topic) && topic <= 0) return false;
    return true;
  });
}

export function buildQueryContract(rawQuery: string): QueryContract {
  const extracted = extractCanonicalQuery(rawQuery);
  const normalized = normalize(extracted);
  const boundary = BOUNDARIES.find((item) => item.triggers.some((term) => normalized.includes(normalize(term))));
  const matched = boundary?.triggers.filter((term) => normalized.includes(normalize(term))) ?? [];
  const canonicalQuery = matched.sort((left, right) => normalize(right).length - normalize(left).length)[0] || extracted;
  const preserved = boundary?.preserve.filter((term) => normalize(canonicalQuery).includes(normalize(term))) ?? [];
  return {
    rawQuery,
    canonicalQuery,
    mustPreserve: boundary ? (preserved.length ? preserved : [canonicalQuery]) : (canonicalQuery ? [canonicalQuery] : []),
    expandedTerms: boundary?.expansions ?? [],
    excludedGeneralizations: boundary?.parents ?? GENERIC_PARENTS,
    semanticBoundary: boundary?.name,
  };
}

export function retrieveQualifiedMentors(
  rawQuery: string,
  candidates: RagMentor[],
  evidenceFor: (candidateId: string) => RagEvidence[],
  options: { fallback?: boolean; limit?: number; threshold?: number; personalize?: boolean } = {},
): { query: QueryContract; matches: MentorMatch[] } {
  const query = buildQueryContract(rawQuery);
  const fallback = options.fallback ?? false;
  const threshold = options.threshold ?? relevanceThreshold();
  const scoreFloor = options.personalize ? threshold : relevanceThreshold();
  const matches: MentorMatch[] = [];
  for (const candidate of candidates) {
    const assessed = assessCandidate(query, candidate, fallback, scoreFloor);
    if (assessed.finalScore < threshold || !['DIRECT', 'ADJACENT'].includes(assessed.matchType)) continue;
    const evidence = bindEvidence(query, candidate, evidenceFor(candidate.candidate_id), assessed.matchType);
    if (!evidence.some((item) => item.support_type === 'DIRECT' || item.support_type === 'ADJACENT')) continue;
    if (publicationContradiction(candidate, evidence)) continue;
    const queryEvidence = evidence.filter((item) => item.support_type !== 'IDENTITY');
    matches.push({
      candidate,
      finalScore: assessed.finalScore,
      matchType: assessed.matchType as 'DIRECT' | 'ADJACENT',
      scoreBreakdown: {
        ...assessed.scoreBreakdown,
        evidence_coverage: queryEvidence.length ? round(Math.min(100, 40 + queryEvidence.length * 20)) : 0,
      },
      evidence,
      matchedTerms: assessed.matchedTerms,
      fallback,
    });
  }
  matches.sort((a, b) => b.finalScore - a.finalScore || a.candidate.candidate_id.localeCompare(b.candidate.candidate_id));
  return { query, matches: matches.slice(0, options.limit ?? 5) };
}

export function reviewMatches(query: QueryContract, matches: MentorMatch[]): ReviewOutcome {
  if (!matches.length) {
    return {
      status: 'NO_MATCH',
      failed_checks: ['no_qualified_match'],
      reviewer_summary: `没有导师达到「${query.canonicalQuery}」的绝对相关性与查询相关证据阈值；系统不会用全库 Top-K 补满。`,
      no_match: true,
    };
  }
  const failed: string[] = [];
  for (const match of matches) {
    if (match.matchType === 'UNRELATED' as string) failed.push(`unrelated:${match.candidate.candidate_id}`);
    if (!match.evidence.some((item) => item.support_type === 'DIRECT' || item.support_type === 'ADJACENT')) {
      failed.push(`missing_query_evidence:${match.candidate.candidate_id}`);
    }
    if (publicationContradiction(match.candidate, match.evidence)) {
      failed.push(`publication_count_contradiction:${match.candidate.candidate_id}`);
    }
  }
  if (failed.length) {
    return {
      status: 'VETO',
      failed_checks: failed,
      reviewer_summary: '审核否决：存在明显无关、缺查询相关证据或论文计数字段矛盾的候选。',
      no_match: false,
    };
  }
  return {
    status: 'PASS',
    failed_checks: [],
    reviewer_summary: '通过绝对相关性、候选级证据绑定与矛盾检查。',
    no_match: false,
  };
}

function assessCandidate(query: QueryContract, candidate: RagMentor, fallback: boolean, scoreFloor = relevanceThreshold()) {
  const boundary = BOUNDARIES.find((item) => item.name === query.semanticBoundary);
  const topics = (candidate.research_topics ?? []).map(normalize);
  const methods = (candidate.methods ?? []).map(normalize);
  const topicAssessment = boundary
    ? boundaryScore(query.canonicalQuery, topics, boundary)
    : overlapAssessment(query, topics);
  const methodAssessment = boundary
    ? boundaryScore(query.canonicalQuery, methods, boundary)
    : overlapAssessment(query, methods);
  const officialTopics = Number(candidate.source_metadata?.topics_source ?? 0) === 1;
  let topicScore = topicAssessment.score * (officialTopics ? 1 : 0.45);
  let matchType = topicAssessment.type;
  if (methodApplicationVeto(query, topics, matchType)) {
    topicScore = 0;
    matchType = 'UNRELATED';
  }
  const fallbackFactor = fallback ? 0.82 : 1;
  const finalScore = round(topicScore * 0.92 * fallbackFactor);
  if (finalScore < scoreFloor) matchType = matchType === 'DIRECT' || matchType === 'ADJACENT' ? 'UNRELATED' : matchType;
  return {
    finalScore,
    matchType,
    matchedTerms: [...new Set([...topicAssessment.matched, ...methodAssessment.matched])],
    scoreBreakdown: {
      topic_match: round(topicScore),
      method_match: 0,
      publication_support: 0,
      evidence_confidence: officialTopics ? 95 : 45,
      fallback_factor: fallbackFactor,
    },
  };
}

function methodApplicationVeto(query: QueryContract, topics: string[], matchType: string): boolean {
  const queryBlob = normalize(`${query.canonicalQuery} ${query.rawQuery}`);
  const topicBlob = topics.join(' ');
  const queryIsMethod = Boolean(query.semanticBoundary);
  const candidateApp = APPLICATION_HINTS.some((hint) => topicBlob.includes(normalize(hint)));
  const queryApp = APPLICATION_HINTS.some((hint) => queryBlob.includes(normalize(hint)));
  if (queryIsMethod && matchType === 'UNRELATED' && candidateApp) return true;
  if (queryIsMethod && matchType !== 'DIRECT' && matchType !== 'ADJACENT' && candidateApp) return true;
  if (queryApp && queryIsMethod === false) return false;
  if (queryIsMethod && !queryApp && candidateApp && matchType !== 'DIRECT' && matchType !== 'ADJACENT') return true;
  return false;
}

function bindEvidence(
  query: QueryContract,
  candidate: RagMentor,
  records: RagEvidence[],
  matchType: string,
): BoundEvidence[] {
  const result: BoundEvidence[] = [];
  for (const record of records) {
    if (record.candidate_id && record.candidate_id !== candidate.candidate_id) continue;
    const supports = String(record.metadata?.supports_fields ?? '').split(',').map((item) => item.trim());
    const querySupport = supports.includes('research_topics') || supports.includes('methods');
    const entityVerified = record.metadata?.identity_verified === true;
    const sourceLevel = sourceLevelFor(record);
    if (querySupport && (!entityVerified || sourceLevel === 'L4' || sourceLevel === 'L5')) continue;
    if (!querySupport && !entityVerified) continue;
    // Official provenance does not make a broad parent concept evidence for a
    // narrower query.  Every topic/method record must contain the canonical
    // query or a typed in-boundary term, except official profile records whose
    // research_topics themselves were already boundary-assessed above.
    if (querySupport && sourceLevel !== 'L1' && !textRelevantToQuery(query, record)) continue;
    result.push({
      evidence_id: record.evidence_id,
      candidate_id: candidate.candidate_id,
      source_type: record.source_type ?? 'unknown',
      source_uri: record.source_uri ?? candidate.homepage ?? '',
      title: record.title ?? '',
      extracted_fact: record.extracted_fact ?? '',
      locator: record.locator,
      retrieved_at: record.retrieved_at,
      freshness: freshnessFor(record),
      confidence: Number(record.confidence ?? 0),
      source_level: sourceLevel,
      support_type: querySupport ? (matchType === 'DIRECT' ? 'DIRECT' : 'ADJACENT') : 'IDENTITY',
      query_relevance: querySupport ? (matchType === 'DIRECT' ? 1 : 0.82) : 0,
      entity_verified: entityVerified,
      query: query.canonicalQuery,
    });
  }
  return result;
}

function publicationContradiction(candidate: RagMentor, evidence: BoundEvidence[]): boolean {
  const pubs = Array.isArray(candidate.publications) ? candidate.publications.length : 0;
  const paperEvidence = evidence.some((item) =>
    /openalex|arxiv|semantic|s2|dblp|paper/.test(String(item.source_type).toLowerCase()),
  );
  return pubs === 0 && paperEvidence;
}

function textRelevantToQuery(query: QueryContract, record: RagEvidence): boolean {
  const blob = normalize(`${record.title ?? ''} ${record.extracted_fact ?? ''}`);
  const terms = [query.canonicalQuery, ...query.mustPreserve, ...query.expandedTerms]
    .map(normalize)
    .filter((term) => term.length >= 2);
  if (!terms.length) return false;
  return terms.some((term) => blob.includes(term));
}

function freshnessFor(record: RagEvidence): string {
  const year = Number(record.metadata?.year);
  if (Number.isFinite(year) && year >= 1900) {
    const current = new Date().getUTCFullYear();
    if (year >= current - 2) return 'current';
    if (year >= current - 5) return 'recent';
    return 'stale';
  }
  const declared = String(record.freshness ?? '');
  if (declared === 'recent' || declared === 'current') return 'unknown';
  return declared || 'unknown';
}

function boundaryScore(canonical: string, values: string[], boundary: Boundary) {
  const exact = normalize(canonical);
  for (const value of values) {
    if (exact && (value === exact || value.includes(exact))) {
      return { score: 100, type: 'DIRECT', matched: [exact] };
    }
  }
  const expansions = boundary.expansions.map(normalize);
  for (const value of values) {
    const term = expansions.find((item) => item && (value === item || value.includes(item)));
    if (term) return { score: 82, type: 'ADJACENT', matched: [term] };
  }
  return { score: 0, type: 'UNRELATED', matched: [] as string[] };
}

function overlapAssessment(query: QueryContract, values: string[]) {
  const q = normalize(query.canonicalQuery);
  const qTokens = new Set(tokens(q));
  let best = 0;
  let matched = '';
  for (const value of values) {
    if (isGenericParent(value) && !isGenericParent(q) && q !== value) continue;
    if (query.excludedGeneralizations.some((parent) => value === normalize(parent))) continue;
    if (value === q || value.includes(q)) return { score: 100, type: 'DIRECT', matched: [value] };
    const valueTokens = new Set(tokens(value));
    const overlap = qTokens.size ? [...qTokens].filter((token) => valueTokens.has(token)).length / qTokens.size : 0;
    if (overlap > best) {
      best = overlap;
      matched = value;
    }
  }
  if (matched && isGenericParent(matched) && !isGenericParent(q)) {
    return { score: 0, type: 'UNRELATED', matched: [] as string[] };
  }
  const score = round(best * 100);
  return { score, type: score >= 80 ? 'DIRECT' : score >= 70 ? 'ADJACENT' : 'UNRELATED', matched: matched ? [matched] : [] };
}

function isGenericParent(value: string): boolean {
  const normalized = normalize(value);
  return GENERIC_PARENTS.some((parent) => normalized === normalize(parent));
}

export function isGenericParentTerm(value: string): boolean {
  return isGenericParent(value);
}

/** 长期兴趣：只保留用户 query 的 canonical，丢掉 expansion 上位词。 */
export function longTermInterestTerms(rawQueries: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of rawQueries) {
    const text = String(raw ?? '').replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const wrapper = /^(请(问|帮我)?|麻烦|帮我)?(想要?)?(找(一下|一找)?|推荐|搜索|检索)?(一下)?(导师|老师|教授|博导)s?$/i;
    if (wrapper.test(text.replace(/[。.!！?？,，]/g, '')) || /(邮政编码|手机版|邮编)/.test(text)) continue;
    const contract = buildQueryContract(text);
    const canonical = contract.canonicalQuery.trim();
    if (!canonical || canonical.length < 2) continue;
    const key = normalize(canonical);
    if (isGenericParent(key)) continue;
    if (contract.excludedGeneralizations.some((parent) => normalize(parent) === key)) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(canonical);
  }
  return result;
}

/** 近期 session：保留用户实际检索的 canonical，仍丢掉纯上位词以免一次检索打爆推荐。 */
export function sessionInterestTerms(rawQueries: string[]): string[] {
  return longTermInterestTerms(rawQueries);
}

function extractCanonicalQuery(raw: string): string {
  let text = String(raw ?? '').replace(/\s+/g, ' ').trim().replace(/[。.!！?？,，]+$/g, '');
  text = text.replace(/^(?:请(?:问|帮我)?|麻烦|帮我)?(?:想要?)?(?:找(?:一下)?|搜索|检索)(?:一下)?(?:做|研究)?/i, '');
  text = text.replace(/(?:方向)?(?:的)?(?:导师|老师|教授|博导)s?$/i, '');
  return text.trim() || String(raw ?? '').trim();
}

function normalize(value: string): string {
  return String(value ?? '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function tokens(value: string): string[] {
  const words: string[] = value.match(/[a-z0-9][a-z0-9\-.]*/g) ?? [];
  const chars = value.match(/[一-鿿]/g) ?? [];
  if (chars.length) {
    words.push(chars.join(''));
    for (let index = 0; index < chars.length - 1; index++) words.push(chars[index] + chars[index + 1]);
  }
  return words;
}

function sourceLevelFor(record: RagEvidence): string {
  const source = String(record.source_type ?? '').toLowerCase();
  if (source.includes('official_faculty_profile')) return 'L1';
  if (source.includes('official_faculty_directory')) return 'L2';
  if (record.metadata?.identity_verified === true && source.includes('paper')) return 'L3';
  if (/(openalex|s2|dblp|arxiv)/.test(source)) return 'L4';
  return 'L5';
}

function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

import type { RagEvidence, RagMentor } from './ragAdvisors';
import { retrievalPolicy } from './retrievalPolicy';

export interface QueryContract {
  rawQuery: string;
  canonicalQuery: string;
  mustPreserve: string[];
  expandedTerms: string[];
  excludedGeneralizations: string[];
  semanticBoundary?: string;
  semanticBoundaries?: string[];
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
  filters?: {
    departments: string[];
    mentorNames: string[];
    recruitmentRequired: boolean;
    undergraduateFriendly: boolean;
  };
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

interface RetrievalVector {
  vector: Map<string, number>;
  text: string;
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

const BOUNDARIES: Boundary[] = retrievalPolicy.concept_families.map((family) => ({
  name: family.id,
  triggers: family.aliases,
  preserve: family.preserve ?? [],
  expansions: [...new Set([...(family.aliases ?? []), ...(family.children ?? [])])],
  parents: family.parents ?? [],
}));

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
  return Number.isFinite(raw) && raw > 0 ? raw : retrievalPolicy.scores.relevance_threshold;
}

/** D/A 当前共同认可的主题来源：官网 profile 或已核验论文标题受控回填。 */
export function isTrustedTopicSource(value: unknown): boolean {
  return [1, 3].includes(Number(value ?? 0));
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
  const filters = extractQueryFilters(rawQuery);
  let semanticQuery = String(rawQuery ?? '');
  for (const name of filters.mentorNames) {
    semanticQuery = semanticQuery.replace(new RegExp(`(?:找|查|查看|介绍)\\s*${name}(?:老师|教授|导师|博导)`, 'g'), ' ');
  }
  for (const value of filters.departments) semanticQuery = semanticQuery.replace(value, ' ');
  semanticQuery = semanticQuery
    .replace(/(?:愿意|正在|可以|能)?(?:招收|招生|招|带).{0,10}(?:本科生|硕士|博士|研究生)/g, ' ')
    .replace(/^(?:我会|我熟悉|我掌握|掌握|熟悉|会用)[^，,。；;]{1,100}[，,。；;]\s*/i, '')
    .replace(/\s+/g, ' ').trim()
    .replace(/^做(?=[一-鿿A-Za-z0-9])/, '');
  const extracted = semanticQuery ? extractCanonicalQuery(semanticQuery) : '';
  const explicitOr = /(?:\b(?:or)\b|或者|或)/i.test(extracted);
  const pieces = extracted.split(/\s*(?:\b(?:and|or)\b|或者|或|和|与|以及|及|、|,|，|;|；|\+|\/)\s*/i).filter(Boolean);
  const concepts = (pieces.length ? pieces : extracted ? [extracted] : []).map((surface, index) => {
    let role = 'CORE_TOPIC';
    let cleaned = surface.trim();
    if (/^(?:用于|应用于|面向)/i.test(cleaned)) {
      role = 'APPLICATION_DOMAIN';
      cleaned = cleaned.replace(/^(?:用于|应用于|面向)\s*/i, '');
    } else if (/^(?:用|使用|采用|基于|通过)/i.test(cleaned)) {
      role = 'METHOD';
      cleaned = cleaned.replace(/^(?:用|使用|采用|基于|通过)\s*/i, '');
    }
    const normalized = normalize(cleaned);
    const boundary = BOUNDARIES.find((item) => item.triggers.some((term) => normalized === normalize(term)));
    const canonical = retrievalPolicy.concept_families.find((item) => item.id === boundary?.name)?.canonical ?? cleaned;
    const preserved = boundary?.preserve.filter((term) => normalized.includes(normalize(term))) ?? [];
    return {
      concept_id: `query_concept_${index + 1}`,
      surface: cleaned,
      canonical,
      role,
      required: role === 'CORE_TOPIC',
      must_preserve: boundary ? (preserved.length ? preserved : [canonical]) : [canonical],
      confidence: 1,
      source: 'text',
      boundary,
    };
  });
  const boundaries = [...new Set(concepts.map((item) => item.boundary?.name).filter((item): item is string => Boolean(item)))];
  const canonicalQuery = concepts.map((item) => item.canonical).join('；');
  return {
    rawQuery,
    canonicalQuery,
    mustPreserve: [...new Set(concepts.flatMap((item) => item.must_preserve ?? []))],
    expandedTerms: [...new Set(concepts.flatMap((item) => item.boundary?.expansions ?? []))],
    excludedGeneralizations: [...new Set(concepts.flatMap((item) => item.boundary?.parents ?? GENERIC_PARENTS))],
    semanticBoundary: concepts.length > 1 ? 'multi_concept' : concepts[0]?.boundary?.name,
    semanticBoundaries: boundaries,
    concepts: concepts.map(({ boundary: _boundary, ...item }) => item),
    logic: explicitOr ? 'OR' : concepts.filter((item) => item.required).length > 1 ? 'AND' : 'OR',
    version: retrievalPolicy.version,
    filters,
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
  const retrievalSignals = buildRetrievalSignals(query, candidates);
  const matches: MentorMatch[] = [];
  for (const candidate of candidates) {
    if (!matchesQueryFilters(query, candidate)) continue;
    const nameMatch = query.filters?.mentorNames.some((name) => normalize(name) === normalize(candidate.mentor_name));
    if (nameMatch && !query.canonicalQuery) {
      const evidence = bindEvidence(query, candidate, evidenceFor(candidate.candidate_id), 'DIRECT');
      matches.push({
        candidate, finalScore: 100, matchType: 'DIRECT',
        scoreBreakdown: { eligibility_score: 100, ranking_score: 100, displayed_topic_score: 100, topic_match: 100 },
        evidence, matchedTerms: [candidate.mentor_name], fallback,
      });
      continue;
    }
    const assessed = assessCandidate(
      query,
      candidate,
      fallback,
      scoreFloor,
      retrievalSignals.get(candidate.candidate_id) ?? 0,
    );
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
  const nameOnly = Boolean(query.filters?.mentorNames.length && !query.canonicalQuery);
  for (const match of matches) {
    if (match.matchType === 'UNRELATED' as string) failed.push(`unrelated:${match.candidate.candidate_id}`);
    if (!nameOnly && !match.evidence.some((item) => item.support_type === 'DIRECT' || item.support_type === 'ADJACENT')) {
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

/**
 * Keep D's recommendation/fallback path on the same deterministic calibration
 * scale as A's lexical retriever.  The JSON RAG candidates do not carry a
 * per-query score, so calculate a small TF-IDF cosine signal over the current
 * candidate pool.  It is only a bounded calibration signal; relation type
 * remains the qualification gate.
 */
function buildRetrievalSignals(
  query: QueryContract,
  candidates: RagMentor[],
): Map<string, number> {
  const documents: RetrievalVector[] = candidates.map((candidate) => {
    const text = candidateDocument(candidate);
    return { text, vector: termVector(text) };
  });
  const documentFrequency = new Map<string, number>();
  for (const item of documents) {
    for (const token of item.vector.keys()) {
      documentFrequency.set(token, (documentFrequency.get(token) ?? 0) + 1);
    }
  }
  const totalDocuments = Math.max(1, documents.length);
  const idf = new Map<string, number>();
  for (const [token, frequency] of documentFrequency) {
    // Keep IDF positive even for common Chinese bigrams; negative weights can
    // make a longer candidate look more similar merely because it repeats a
    // ubiquitous token.
    idf.set(token, Math.log((totalDocuments + 1) / (frequency + 1)) + 1);
  }
  const queryText = [query.canonicalQuery, ...query.expandedTerms].join(' ');
  const queryVector = weightedVector(termVector(queryText), idf);
  const queryTerms = [...new Set([query.canonicalQuery, ...query.expandedTerms]
    .map(normalize)
    .filter((term) => term.length >= 2))];
  const signals = new Map<string, number>();

  candidates.forEach((candidate, index) => {
    const metadata = candidate.source_metadata ?? {};
    const denseScore = Number((metadata as Record<string, unknown>).dense_score);
    const retrieveScore = Number((metadata as Record<string, unknown>).retrieve_score);
    let signal: number;
    if (Number.isFinite(denseScore) && denseScore > 0) {
      // Dense scores from A's fusion layer are already normalized to 0..1.
      signal = denseScore;
    } else if (Number.isFinite(retrieveScore) && retrieveScore > 0) {
      // Lexical retrievers expose the same 0..100 score used by A.
      signal = retrieveScore / 35;
    } else {
      const lexicalSimilarity = cosineSimilarity(
        queryVector,
        weightedVector(documents[index].vector, idf),
      );
      const lexicalText = normalize(documents[index].text);
      const lexicalHits = queryTerms.filter((term) => lexicalText.includes(term)).length;
      // Cosine is already a 0..1 signal. A small exact-term bonus mirrors the
      // lexical hit component without allowing every direct match to saturate.
      signal = lexicalSimilarity * 0.9 + Math.min(0.1, lexicalHits * 0.03);
    }
    signals.set(candidate.candidate_id, Math.max(0, Math.min(1, signal)));
  });
  return signals;
}

function candidateDocument(candidate: RagMentor): string {
  return [
    candidate.mentor_name,
    ...(candidate.research_topics ?? []),
    ...(candidate.methods ?? []),
    ...(candidate.publications ?? []),
    candidate.department ?? '',
  ].join(' ');
}

function termVector(text: string): Map<string, number> {
  const counts = new Map<string, number>();
  for (const token of tokens(text)) counts.set(token, (counts.get(token) ?? 0) + 1);
  const peak = Math.max(1, ...counts.values());
  return new Map([...counts].map(([token, count]) => [token, count / peak]));
}

function weightedVector(vector: Map<string, number>, idf: Map<string, number>): Map<string, number> {
  return new Map([...vector].map(([token, weight]) => [token, weight * (idf.get(token) ?? 0)]));
}

function cosineSimilarity(left: Map<string, number>, right: Map<string, number>): number {
  if (!left.size || !right.size) return 0;
  let dot = 0;
  for (const [token, weight] of left) dot += weight * (right.get(token) ?? 0);
  if (dot <= 0) return 0;
  const leftNorm = Math.sqrt([...left.values()].reduce((sum, value) => sum + value * value, 0));
  const rightNorm = Math.sqrt([...right.values()].reduce((sum, value) => sum + value * value, 0));
  return leftNorm && rightNorm ? dot / (leftNorm * rightNorm) : 0;
}

function assessCandidate(
  query: QueryContract,
  candidate: RagMentor,
  fallback: boolean,
  scoreFloor = relevanceThreshold(),
  retrievalSignal = 0,
) {
  const topics = (candidate.research_topics ?? []).map(normalize);
  const methodsVerified = candidate.source_metadata?.methods_verified === true;
  const methods = methodsVerified ? (candidate.methods ?? []).map(normalize) : [];
  const concepts = query.concepts?.length ? query.concepts : [{ canonical: query.canonicalQuery, role: 'CORE_TOPIC', required: true }];
  const assessments = concepts.map((concept) => {
    const canonical = String(concept.canonical ?? concept.surface ?? '');
    const boundary = BOUNDARIES.find((item) => item.triggers.some((term) => normalize(term) === normalize(canonical)));
    // A user phrase such as "用大语言模型" is classified as a METHOD, but a
    // mentor often states that method inside verified research_topics (for
    // example "大语言模型（LLMs）方法及应用") rather than in a separate
    // methods field. When no verified methods exist, fall back to topics so
    // method-style queries still recall those mentors.
    const isMethod = concept.role === 'METHOD';
    const methodTopicFallback = isMethod && !methods.length;
    const values = isMethod && !methodTopicFallback ? methods : topics;
    const singleQuery: QueryContract = { ...query, canonicalQuery: canonical, concepts: [concept] };
    const assessed = boundary ? boundaryScore(canonical, values, boundary) : overlapAssessment(singleQuery, values);
    return { concept, assessed, methodTopicFallback };
  });
  const required = assessments.filter((item) => item.concept.required !== false);
  const considered = required.length ? required : assessments;
  const chosen = query.logic === 'AND'
    ? considered.reduce((left, right) => left.assessed.score <= right.assessed.score ? left : right)
    : considered.reduce((left, right) => left.assessed.score >= right.assessed.score ? left : right);
  const allQualifying = query.logic === 'AND'
    ? considered.every((item) => item.assessed.type === 'DIRECT' || item.assessed.type === 'ADJACENT')
    : considered.some((item) => item.assessed.type === 'DIRECT' || item.assessed.type === 'ADJACENT');
  const trustedTopics = isTrustedTopicSource(candidate.source_metadata?.topics_source);
  const methodOnly = considered.every((item) => item.concept.role === 'METHOD');
  const methodTopicFallback = methodOnly && considered.some((item) => item.methodTopicFallback === true);
  const trustedChannel = methodOnly ? (methodsVerified || (methodTopicFallback && trustedTopics)) : trustedTopics;
  let topicScore = chosen.assessed.score * (trustedChannel ? 1 : retrievalPolicy.scores.untrusted_topic_factor);
  let matchType = allQualifying ? chosen.assessed.type : 'UNRELATED';
  if (methodApplicationVeto(query, topics, matchType)) {
    topicScore = 0;
    matchType = 'UNRELATED';
  }
  const fallbackFactor = fallback ? retrievalPolicy.scores.fallback_factor : 1;
  const boundedRetrievalSignal = Math.max(0, Math.min(1, retrievalSignal));
  const calibrationFactor = retrievalPolicy.scores.topic_calibration
    + (1 - retrievalPolicy.scores.topic_calibration) * boundedRetrievalSignal;
  const finalScore = round(topicScore * calibrationFactor * fallbackFactor);
  if (finalScore < scoreFloor) matchType = matchType === 'DIRECT' || matchType === 'ADJACENT' ? 'UNRELATED' : matchType;
  return {
    finalScore,
    matchType,
    matchedTerms: [...new Set(assessments.flatMap((item) => item.assessed.matched))],
    scoreBreakdown: {
      eligibility_score: finalScore,
      ranking_score: finalScore,
      displayed_topic_score: round(Math.max(0, ...assessments.filter((item) => item.concept.role !== 'METHOD').map((item) => item.assessed.score))),
      topic_match: round(topicScore),
      method_match: round(Math.max(0, ...assessments.filter((item) => item.concept.role === 'METHOD').map((item) => item.assessed.score))),
      publication_support: 0,
      evidence_confidence: trustedChannel ? 95 : 45,
      fallback_factor: fallbackFactor,
      retrieval_signal: round(boundedRetrievalSignal * 100),
      calibration_factor: round(calibrationFactor, 4),
    },
  };
}

function methodApplicationVeto(query: QueryContract, topics: string[], matchType: string): boolean {
  const queryBlob = normalize(`${query.canonicalQuery} ${query.rawQuery}`);
  const topicBlob = topics.join(' ');
  const queryIsMethod = Boolean(query.concepts?.some((concept) => concept.role === 'METHOD'));
  const candidateApp = APPLICATION_HINTS.some((hint) => topicBlob.includes(normalize(hint)));
  const queryApp = APPLICATION_HINTS.some((hint) => queryBlob.includes(normalize(hint)));
  if (queryIsMethod && matchType === 'UNRELATED' && candidateApp) return true;
  if (queryIsMethod && matchType !== 'DIRECT' && matchType !== 'ADJACENT' && candidateApp) return true;
  if (queryApp && queryIsMethod === false) return false;
  if (queryIsMethod && !queryApp && candidateApp && matchType !== 'DIRECT' && matchType !== 'ADJACENT') return true;
  return false;
}

function extractQueryFilters(rawQuery: string): NonNullable<QueryContract['filters']> {
  const departments = [...String(rawQuery ?? '').matchAll(/([一-鿿A-Za-z0-9·\-]{2,30}(?:学院|系(?!统)|研究院|实验室))/g)]
    .map((match) => match[1].replace(/^(?:找|在|来自)/, ''));
  const mentorNames = [...String(rawQuery ?? '').matchAll(/(?:找|查|查看|介绍)\s*([一-鿿]{2,3})(?:老师|教授|导师|博导)/g)]
    .map((match) => match[1]);
  return {
    departments: [...new Set(departments)],
    mentorNames: [...new Set(mentorNames)],
    recruitmentRequired: /(?:愿意|正在|可以|能)?(?:招收|招生|招|带).{0,8}(?:本科生|硕士|博士|研究生)/.test(rawQuery),
    undergraduateFriendly: /(?:愿意|可以|能|招|带).{0,8}本科生/.test(rawQuery),
  };
}

function matchesQueryFilters(query: QueryContract, candidate: RagMentor): boolean {
  const filters = query.filters;
  if (!filters) return true;
  if (filters.mentorNames.length && !filters.mentorNames.some((name) => normalize(name) === normalize(candidate.mentor_name))) return false;
  const department = normalize(candidate.department ?? '');
  if (filters.departments.length && !filters.departments.some((value) => department.includes(normalize(value)) || normalize(value).includes(department))) return false;
  const recruitment = String(candidate.recruitment_status ?? '');
  if (filters.recruitmentRequired && !recruitment) return false;
  if (filters.undergraduateFriendly && !recruitment.includes('本科')) return false;
  return true;
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
  const preserved = boundary.preserve.map(normalize).filter(Boolean);
  if (preserved.length >= 2) {
    for (const value of values) {
      if (preserved.every((term) => value.includes(term))) {
        return { score: retrievalPolicy.scores.adjacent_relation, type: 'ADJACENT', matched: preserved };
      }
    }
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
  text = text.replace(/^(?:请(?:问|帮我)?|麻烦|帮我)?\s*(?:想要?)?\s*(?:找(?:一下)?|搜索|检索)\s*(?:一下)?\s*(?:做|研究)?\s*/i, '');
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

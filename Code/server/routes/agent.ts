import { Router, Response } from 'express';
import multer from 'multer';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { rateLimit } from '../middleware/rateLimit';
import {
  enqueuePendingGrowthWrite,
  findPendingGrowthWrite,
  listPendingGrowthWrites,
  loadTrustedAgentContext,
  updatePendingGrowthWrite,
  type ReviewedGrowthWrite,
} from '../data/growthStore';
import {
  listRunArtifacts,
  loadRunArtifactByRunId,
  saveRunArtifact,
} from '../data/runArtifacts';
import { persistUploadedPdf, loadResearchDocument } from '../data/researchDocuments';
import { cleanTopics } from '../data/topicBoilerplate';
import { getDb } from '../db';
import { getLlmApiSettings } from '../services/llmSettings';
import { ragStore, ragData, toLightAdvisor } from '../data/ragAdvisors';
import { retrieveQualifiedMentors, reviewMatches, relevanceThreshold, keepDisplayableAdvisors, longTermInterestTerms } from '../data/mentorRetrieval';
import { extractPdfPages, extractPdfText } from './pdfText';
import { reconcileProgressReport } from './reports';
import {
  agentBase,
  agentPollMs,
  agentTimeoutMs,
  agentUrl,
  commitHarnessPass,
  emailGrowthPatch,
  isNumericRunId,
  paperGrowthPatch,
  pdfGrowthPatch,
  postHarnessRun,
  probeAgent,
  runHarnessSkill,
  suggestNextSkill,
} from '../harnessClient';

export const agentRouter = Router();

agentRouter.use(authMiddleware);
agentRouter.use(rateLimit({ windowMs: 60_000, max: 12, label: 'agent-chat' }));

const EVENT_HINT: Record<string, string> = {
  INPUT_RECEIVED: '已收到需求，正在理解意图',
  INTENT_READY: '意图已确认，正在规划',
  PLAN_READY: '计划已生成，正在调用领域专家',
  DOMAIN_ANALYSIS_STARTED: '领域专家开始分析',
  DOMAIN_ANALYSIS_READY: '领域判断完成',
  RESEARCH_STARTED: '导师研究 Agent 开始检索语料',
  RESEARCH_DONE: '导师研究完成',
  MATCHING_STARTED: '匹配 Agent 正在打分',
  MATCHING_DONE: '匹配完成',
  REVIEW_STARTED: '独立审核开始',
  REVIEW_PASSED: '审核通过',
  REVIEW_FAILED: '审核未通过，准备返工',
  TASK_RETRY: 'Retry：按审核意见重新执行',
  COMPOSING_RESULT: '正在汇总结果',
  RESULT_READY: '结果已生成',
  WORKFLOW_COMPLETED: '本轮多智能体任务完成',
  WORKFLOW_FAILED: '本轮任务失败',
  QUERY_CONTRACT_READY: '查询约束已冻结',
  RETRIEVAL_PLAN_READY: '检索管理器已生成多路检索计划',
  RETRIEVER_STARTED: '开始执行受控召回',
  RETRIEVER_COMPLETED: '召回完成，正在核对覆盖度',
  RETRIEVAL_RETRY: '质量门未通过，按原查询重新检索',
  QUALITY_GATE_PASSED: '相关性与证据质量门通过',
  NO_QUALIFIED_MATCH: '没有达到查询阈值的导师',
};

const SILENCED_A_EVENTS = new Set([
  'WORKFLOW_COMPLETED',
  'WORKFLOW_FAILED',
  'RESULT_READY',
]);

function stripResultFields(payload?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!payload) return payload;
  const next = { ...payload };
  delete next.mentors;
  delete next.match_results;
  delete next.evidence_ledger;
  delete next.review_decision;
  delete next.records;
  return next;
}

function inferStageFromEvent(eventType: string, sender?: string): string | undefined {
  const start: Record<string, string> = {
    WORKFLOW_CREATED: 'input_understanding',
    WORKFLOW_RESUMED: 'input_understanding',
    INPUT_RECEIVED: 'input_understanding',
    CLARIFICATION_REQUIRED: 'input_understanding',
    DOMAIN_ANALYSIS_STARTED: 'domain_expert',
    RESEARCH_STARTED: 'mentor_research',
    RETRIEVAL_PLAN_READY: 'mentor_research',
    RETRIEVER_STARTED: 'mentor_research',
    RETRIEVAL_RETRY: 'mentor_research',
    MATCHING_STARTED: 'matching',
    REVIEW_STARTED: 'evidence_review',
    COMPOSING_RESULT: 'result_composer',
  };
  const complete: Record<string, string> = {
    INTENT_READY: 'input_understanding',
    QUERY_CONTRACT_READY: 'input_understanding',
    PLAN_READY: 'planning',
    DOMAIN_ANALYSIS_READY: 'domain_expert',
    RESEARCH_DONE: 'mentor_research',
    RETRIEVER_COMPLETED: 'mentor_research',
    CANDIDATES_FUSED: 'mentor_research',
    QUALITY_GATE_PASSED: 'mentor_research',
    NO_QUALIFIED_MATCH: 'mentor_research',
    MATCHING_DONE: 'matching',
    RELATION_JUDGED: 'matching',
    REVIEW_PASSED: 'evidence_review',
    REVIEW_FAILED: 'evidence_review',
    EVIDENCE_READY: 'evidence_review',
    RESULT_READY: 'result_composer',
  };
  if (start[eventType]) return start[eventType];
  if (complete[eventType]) return complete[eventType];
  if (eventType === 'WORKFLOW_COMPLETED') return 'completed';
  if (eventType === 'WORKFLOW_FAILED') return 'failed';
  if (eventType === 'TASK_RETRY') return 'mentor_research';
  const s = String(sender || '').toLowerCase();
  if (s.includes('input_understanding') || s.includes('intake')) return 'input_understanding';
  if (s.includes('planning')) return 'planning';
  if (s.includes('domain')) return 'domain_expert';
  if (s.includes('mentor_research') || s.includes('retrieval')) return 'mentor_research';
  if (s.includes('matching')) return 'matching';
  if (s.includes('evidence_review') || s.includes('review')) return 'evidence_review';
  if (s.includes('result_composer') || s.includes('composer')) return 'result_composer';
  return undefined;
}

function sse(res: Response, event: string, data: unknown): void {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  const flushable = res as Response & { flush?: () => void };
  if (typeof flushable.flush === 'function') flushable.flush();
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface RuntimeEvent {
  event_type: string;
  stage?: string;
  payload?: Record<string, unknown>;
  evidence_refs?: string[];
  state_version?: number;
  timestamp?: string;
  sender?: string;
  receiver?: string;
  message?: string;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
let _stmts: { insertMission: any; insertEvent: any; updateMission: any } | null = null;

function ensureStmts(): void {
  if (_stmts) return;
  const db = getDb();
  _stmts = {
    insertMission: db.prepare(
      `INSERT INTO missions (user_id, trace_id, query, status, goal, advisor_ids, source)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ),
    insertEvent: db.prepare(
      `INSERT INTO mission_events
        (mission_id, seq, event_type, stage, sender, receiver, payload, evidence_refs, state_version)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ),
    updateMission: db.prepare(
      `UPDATE missions SET status = ?, advisor_ids = ?, updated_at = datetime('now','localtime') WHERE id = ?`,
    ),
  };
}

function createMission(userId: number, traceId: string, query: string, source: string): number | null {
  try {
    ensureStmts();
    const r = _stmts!.insertMission.run(userId, traceId, query, 'RUNNING', '', '[]', source);
    return Number(r.lastInsertRowid);
  } catch {
    return null;
  }
}

function persistEvent(missionId: number | null, seq: number, ev: RuntimeEvent): void {
  if (missionId == null) return;
  try {
    ensureStmts();
    _stmts!.insertEvent.run(
      missionId,
      seq,
      ev.event_type,
      ev.stage ?? '',
      ev.sender ?? '',
      ev.receiver ?? '',
      JSON.stringify(ev.payload ?? {}),
      JSON.stringify(ev.evidence_refs ?? []),
      ev.state_version ?? null,
    );
  } catch {
    /* 落库失败不阻断 SSE */
  }
}

function finalizeMission(missionId: number | null, status: string, advisorIds: string[]): void {
  if (missionId == null) return;
  try {
    ensureStmts();
    _stmts!.updateMission.run(status, JSON.stringify(advisorIds), missionId);
  } catch {
    /* ignore */
  }
}
/* eslint-enable @typescript-eslint/no-explicit-any */

interface StagePayload {
  event_type: string;
  summary: string;
  sender?: string;
  receiver?: string;
  timestamp?: string;
  payload?: Record<string, unknown>;
  evidence_refs?: string[];
}

function mapFinalMentor(m: any, index: number): any {
  const candidate = m?.candidate ?? {};
  const match = m?.match ?? {};
  const candidateEvidence: any[] = Array.isArray(m?.evidence) ? m.evidence : [];
  // C 侧只把已确认作者的代表作写入 candidate；论文总数使用来源平台的独立口径。
  const pubList: unknown[] = Array.isArray(candidate.publications) ? candidate.publications : [];
  const sourcePublicationTotal = Number(candidate.source_metadata?.publication_total_count);
  const evidenceRefs = [
    ...(Array.isArray(candidate.evidence_refs) ? candidate.evidence_refs : []),
    ...(Array.isArray(match.evidence_refs) ? match.evidence_refs : []),
  ].filter((value, pos, all) => typeof value === 'string' && all.indexOf(value) === pos);
  const retrieveMode = candidate.source_metadata?.retrieve_mode;
  const topicScore = Number(
    match.dimension_scores?.research_topic_match ?? match.total_score ?? 0,
  );
  // `research_topic_match` is deliberately coarse (many direct matches are
  // 100).  The UI score should instead reflect the workflow's eight-dimension
  // aggregate, while the topic score remains available in scoreBreakdown.
  const workflowScore = Number(match.total_score);
  const displayScore = Number.isFinite(workflowScore) ? workflowScore : topicScore;
  return {
    id: candidate.candidate_id ?? String(index + 1),
    name: candidate.mentor_name ?? '未知导师',
    title: candidate.source_metadata?.academic_title ?? '',
    department: candidate.department ?? '',
    tags: cleanTopics(
      Array.isArray(candidate.research_topics) ? candidate.research_topics : [],
    ),
    papers: Number.isFinite(sourcePublicationTotal) && sourcePublicationTotal >= 0
      ? sourcePublicationTotal : pubList.length,
    publications: pubList,
    // Preserve one decimal place from A's calibrated score.  Integer rounding
    // collapsed distinct evidence/retrieval signals (for example 97.9 and
    // 98.4) into the same visible grade.
    matchScore: Math.round(displayScore * 10) / 10,
    scoreKind: 'workflow_match',
    matchType: match.match_type ?? candidate.source_metadata?.match_type ?? 'UNASSESSED',
    scoreBreakdown: match.score_breakdown ?? {},
    confidence: Number(match.confidence ?? topicScore / 100),
    explanation: Array.isArray(match.rationale) ? match.rationale.join('\n') : undefined,
    evidenceRefs,
    evidence: candidateEvidence,
  };
}

function extractCurrentIntentTopics(query: string): string[] {
  return longTermInterestTerms([query]);
}

function mentorGrowthPatch(
  runId: string,
  advisors: any[],
  evidenceRefs: string[],
  query = '',
): ReviewedGrowthWrite['patch'] {
  const directions = extractCurrentIntentTopics(query);
  return {
    matched_mentors: advisors.map((advisor) => ({
      id: advisor.id,
      name: advisor.name,
      tags: advisor.tags,
      evidence_refs: advisor.evidenceRefs?.length ? advisor.evidenceRefs : evidenceRefs,
    })),
    directions,
    direction_hypotheses: directions.map((direction) => ({
      id: `direction:${String(direction).trim().toLowerCase()}`,
      direction,
      status: 'supported',
      evidence_refs: evidenceRefs,
      updated_at: new Date().toISOString(),
    })),
    verified_experiences: [{
      id: `mentor-match:${runId}`,
      type: 'mentor_match',
      summary: `完成 ${advisors.length} 位导师的证据审核匹配`,
      evidence_refs: evidenceRefs,
      verified_at: new Date().toISOString(),
    }],
    artifacts: [{
      id: `mentor-match:${runId}`,
      type: 'mentor_match_result',
      title: '导师匹配结果',
      mentor_ids: advisors.map((advisor) => advisor.id),
      evidence_refs: evidenceRefs,
    }],
    research_tasks: advisors.slice(0, 3).map((advisor) => ({
      id: `read-mentor:${advisor.id}`,
      title: `阅读 ${advisor.name} 的代表论文`,
      status: 'pending',
      acceptance_criteria: ['至少形成 2 条论文证据', '记录一个可继续研究的问题'],
      mentor_id: advisor.id,
      evidence_refs: advisor.evidenceRefs?.length ? advisor.evidenceRefs : evidenceRefs,
    })),
  };
}

interface ParsedDocumentInput {
  source_ref: string;
  summary: string;
  research_topics: string[];
  methods: string[];
  application_domains: string[];
}

/** 把 v1.1 已落库的 PDF（upload_id = document_id）抽成 A 可消费的 parsed_documents。 */
async function buildParsedDocuments(uploadId: string, userId: number): Promise<ParsedDocumentInput[]> {
  try {
    const rec = loadResearchDocument(userId, uploadId);
    if (!rec || !fs.existsSync(rec.storedPath)) return [];
    const docText = rec.extractedText?.trim()
      ? rec.extractedText
      : await extractPdfText(rec.storedPath);
    if (!docText.trim()) return [];
    const summary = docText.replace(/\s+/g, ' ').trim().slice(0, 600) || rec.originalName;
    return [{
      source_ref: rec.originalName || uploadId,
      summary: summary.length >= 600 ? `${summary}…` : summary,
      // Do not infer the document topic from whichever mentors happen to be
      // retrieved. That circular path contaminated Query Expansion.
      research_topics: [],
      methods: [],
      application_domains: [],
    }];
  } catch {
    return [];
  }
}

/** 从已合格导师的 candidate.evidence[] 映射 Evidence Ledger，不再透传 A 的全局证据池。 */
function mapHarnessEvidenceLedger(_records: any[], advisors: any[], limit = 12): unknown[] {
  return advisors.flatMap((advisor: any) =>
    (Array.isArray(advisor?.evidence) ? advisor.evidence : []).filter((item: any) =>
      (item?.support_type === 'DIRECT' || item?.support_type === 'ADJACENT')
      && item?.candidate_id
      && Number(item?.query_relevance ?? 0) > 0
      && item?.source_level !== 'L5',
    ),
  ).map((item: any) => ({
    evidence_id: item.evidence_id,
    candidate_id: item.candidate_id,
    source_type: item.source_type,
    source_uri: item.source_uri,
    title: item.title,
    extracted_fact: item.extracted_fact,
    locator: item.locator,
    retrieved_at: item.retrieved_at,
    freshness: item.freshness,
    confidence: item.confidence,
    query: item.query,
    query_relevance: item.query_relevance,
    entity_verified: item.entity_verified,
    support_type: item.support_type,
    source_level: item.source_level,
  })).slice(0, limit);
}

async function createMentorRun(
  message: string,
  context: Record<string, unknown>,
): Promise<{ traceId: string; runId: string } | { error: string }> {
  const base = agentBase().replace(/\/+$/, '');
  try {
    const runRes = await fetch(`${base}/api/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        skill_id: 'mentor_match',
        message,
        execute_immediately: false,
        context: {
          user_id: context.user_id ?? null,
          query: message,
          profile: context.profile ?? {},
          growth: context.growth ?? {},
          parsed_documents: context.parsed_documents ?? [],
        },
      }),
      signal: AbortSignal.timeout(agentTimeoutMs()),
    });
    if (runRes.ok) {
      const created: any = await runRes.json();
      const traceId = String(created?.trace_id || '');
      const runId = String(created?.run_id || '');
      if (traceId) return { traceId, runId };
    }
  } catch {
    /* /api/runs 不可用时回退 mentor-workflows */
  }

  const createRes = await fetch(`${base}/api/mentor-workflows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      execute_immediately: false,
      parsed_documents: Array.isArray(context.parsed_documents) ? context.parsed_documents : [],
    }),
    signal: AbortSignal.timeout(agentTimeoutMs()),
  });
  if (!createRes.ok) {
    const txt = await createRes.text().catch(() => '');
    return { error: `创建工作流失败 (${createRes.status}): ${txt.slice(0, 200)}` };
  }
  const created: any = await createRes.json();
  const traceId: string | undefined = created?.trace_id;
  if (!traceId) return { error: 'A 后端未返回 trace_id' };
  return { traceId, runId: String(created?.run_id || '') };
}

async function resumeMentorRun(traceId: string, message: string): Promise<{ error?: string }> {
  const res = await fetch(agentUrl(`/api/mentor-workflows/${encodeURIComponent(traceId)}/input-async`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
    signal: AbortSignal.timeout(agentTimeoutMs()),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    return { error: `续跑工作流失败 (${res.status}): ${txt.slice(0, 200)}` };
  }
  return {};
}

async function collectMentorResult(traceId: string): Promise<{
  advisors: any[];
  reviewStatus: string;
  evidenceRefs: string[];
  evidenceRecords: any[];
  queryContract: any;
  retrievalAttempts: any[];
  relationJudgements: any[];
  coverageReport: Record<string, unknown>;
  noMatchDiagnostics: Record<string, unknown>;
} | { error: string }> {
  const resultRes = await fetch(agentUrl(`/api/mentor-workflows/${encodeURIComponent(traceId)}/result`), {
    signal: AbortSignal.timeout(agentTimeoutMs()),
  });
  if (!resultRes.ok) return { error: `获取检索结果失败 (${resultRes.status})` };
  const data: any = await resultRes.json();
  const reviewRes = await fetch(agentUrl(`/api/mentor-workflows/${encodeURIComponent(traceId)}/review`), {
    signal: AbortSignal.timeout(agentTimeoutMs()),
  });
  if (!reviewRes.ok) return { error: `获取审核结果失败 (${reviewRes.status})` };
  const review: any = await reviewRes.json();
  const reviewStatus = String(review?.status || '');
  const evidenceRes = await fetch(agentUrl(`/api/mentor-workflows/${encodeURIComponent(traceId)}/evidence`), {
    signal: AbortSignal.timeout(agentTimeoutMs()),
  });
  const evidenceRecords: any[] = evidenceRes.ok
    ? await evidenceRes.json().catch(() => [])
    : [];
  const mentors: any[] = Array.isArray(data?.mentors) ? data.mentors : [];
  const noMatch = reviewStatus === 'NO_MATCH' || (Array.isArray(review?.failed_checks) && review.failed_checks.includes('no_qualified_match'));
  if (reviewStatus !== 'PASS' && !noMatch) {
    return { error: `导师结果未通过审核 (${reviewStatus || 'UNKNOWN'})` };
  }
  const advisors = noMatch
    ? []
    : keepDisplayableAdvisors(
      mentors
        .map(mapFinalMentor)
        .filter((a: any) => a.name !== '未知导师'),
    );
  const evidenceRefs = [
    ...(Array.isArray(data?.evidence_refs) ? data.evidence_refs : []),
    ...(Array.isArray(review?.missing_evidence_refs) ? review.missing_evidence_refs : []),
    ...evidenceRecords.map((record) => record?.evidence_id),
    ...advisors.flatMap((advisor: any) => advisor.evidenceRefs ?? []),
  ].filter((value, pos, all) => typeof value === 'string' && all.indexOf(value) === pos);
  return {
    advisors,
    reviewStatus: noMatch ? 'NO_MATCH' : reviewStatus,
    evidenceRefs,
    evidenceRecords,
    queryContract: data?.query_contract ?? {},
    retrievalAttempts: Array.isArray(data?.retrieval_attempts) ? data.retrieval_attempts : [],
    relationJudgements: Array.isArray(data?.relation_judgements) ? data.relation_judgements : [],
    coverageReport: data?.coverage_report && typeof data.coverage_report === 'object'
      ? data.coverage_report
      : {},
    noMatchDiagnostics: data?.no_match_diagnostics && typeof data.no_match_diagnostics === 'object'
      ? data.no_match_diagnostics
      : {},
  };
}

function commitMentorPass(
  userId: number,
  runId: string,
  traceId: string,
  query: string,
  collected: {
    advisors: any[];
    reviewStatus: string;
    evidenceRefs: string[];
    evidenceRecords: any[];
  },
): void {
  if (!isNumericRunId(runId)) {
    throw new Error('成长状态只接受数值 AgentRun id，拒绝把 trace_id 当 run_id 写入');
  }
  commitHarnessPass({
    userId,
    runId,
    skillId: 'mentor_match',
    query,
    result: {
      review_status: collected.reviewStatus,
      evidence_refs: collected.evidenceRefs,
      advisors: collected.advisors,
      evidence_records: collected.evidenceRecords,
    },
    patch: mentorGrowthPatch(runId, collected.advisors, collected.evidenceRefs, query),
    traceId,
  });
}

async function proxyToMentorAgent(
  message: string,
  context: Record<string, unknown>,
  onStage: (payload: StagePayload) => void,
  isCancelled: () => boolean = () => false,
  resumeTraceId?: string,
): Promise<
  | {
      ok: true;
      advisors: any[];
      summary: string;
      run_id: string;
      trace_id: string;
      review_status: string;
      evidence_refs: string[];
      evidence_records?: any[];
      query_contract?: any;
      retrieval_attempts?: any[];
      relation_judgements?: any[];
      coverage_report?: Record<string, unknown>;
      no_match_diagnostics?: Record<string, unknown>;
      suggested_next_skill?: string | null;
    }
  | { ok: false; error: string }
  | { ok: true; clarification: string[]; trace_id: string; run_id: string }
> {
  const base = agentBase().replace(/\/+$/, '');
  const userId = Number(context.user_id);
  try {
    let traceId = resumeTraceId || '';
    let runId = '';
    if (resumeTraceId && Number.isFinite(userId)) {
      const pending = findPendingGrowthWrite({
        userId,
        skillId: 'mentor_match',
        traceId: resumeTraceId,
      });
      if (pending?.runId && isNumericRunId(pending.runId)) runId = pending.runId;
    }
    if (resumeTraceId) {
      const resumed = await resumeMentorRun(resumeTraceId, message);
      if (resumed.error) return { ok: false, error: resumed.error };
    } else {
      const created = await createMentorRun(message, context);
      if ('error' in created) return { ok: false, error: created.error };
      traceId = created.traceId;
      runId = isNumericRunId(created.runId) ? created.runId : '';
      const startRes = await fetch(
        `${base}/api/mentor-workflows/${encodeURIComponent(traceId)}/resume-async`,
        { method: 'POST', signal: AbortSignal.timeout(10000) },
      );
      if (!startRes.ok) {
        const detail = await startRes.text().catch(() => '');
        return { ok: false, error: `启动导师工作流失败 (${startRes.status}): ${detail.slice(0, 200)}` };
      }
    }

    const pendingId = Number.isFinite(userId)
      ? enqueuePendingGrowthWrite({
          userId,
          skillId: 'mentor_match',
          runId: runId || null,
          traceId,
          query: message,
          status: 'polling',
        })
      : 0;

    const seen = new Set<string>();
    const deadline = Date.now() + agentTimeoutMs();
    let status = 'PENDING';
    let clarification: string[] = [];

    while (Date.now() < deadline && !isCancelled()) {
      await sleep(agentPollMs());
      try {
        const evRes = await fetch(`${base}/api/mentor-workflows/${traceId}/events`, {
          signal: AbortSignal.timeout(agentPollMs() * 2),
        });
        if (evRes.ok) {
          const events: any[] = await evRes.json();
          for (const ev of events || []) {
            const key = String(ev?.message_id || `${ev?.event_type}-${ev?.timestamp || ''}`);
            if (seen.has(key)) continue;
            seen.add(key);
            const eventType = String(ev?.event_type || '');
            onStage({
              event_type: eventType,
              summary: EVENT_HINT[eventType] || eventType,
              sender: typeof ev?.sender === 'string' ? ev.sender : undefined,
              receiver: typeof ev?.receiver === 'string' ? ev.receiver : undefined,
              timestamp: typeof ev?.timestamp === 'string' ? ev.timestamp : undefined,
              payload: ev?.payload && typeof ev.payload === 'object' ? ev.payload : {},
              evidence_refs: Array.isArray(ev?.evidence_refs)
                ? ev.evidence_refs.filter((item: unknown) => typeof item === 'string')
                : [],
            });
            await sleep(30);
          }
        }
      } catch {
        /* ignore poll miss */
      }

      try {
        const stRes = await fetch(`${base}/api/mentor-workflows/${traceId}/status`, {
          signal: AbortSignal.timeout(agentPollMs() * 2),
        });
        if (stRes.ok) {
          const st: any = await stRes.json();
          status = st?.status ?? status;
          if (status === 'CLARIFICATION_REQUIRED') {
            const qs: unknown = st?.clarification_request?.questions;
            clarification = Array.isArray(qs)
              ? qs.map((q) => String(q)).filter(Boolean)
              : [];
          }
          if (status === 'COMPLETED' || status === 'FAILED' || status === 'CLARIFICATION_REQUIRED') break;
        }
      } catch {
        /* ignore */
      }
    }

    if (status === 'CLARIFICATION_REQUIRED') {
      if (pendingId) updatePendingGrowthWrite(pendingId, { status: 'waiting_input', runId: runId || null });
      return { ok: true, clarification, trace_id: traceId, run_id: runId };
    }
    if (status !== 'COMPLETED') {
      if (pendingId) {
        updatePendingGrowthWrite(pendingId, {
          status: status === 'FAILED' ? 'failed' : 'pending_reconcile',
        });
      }
      return {
        ok: false,
        error: status === 'FAILED' ? '检索工作流失败' : 'A 端检索耗时较长，超过等待时间',
      };
    }

    const collected = await collectMentorResult(traceId);
    if ('error' in collected) {
      if (pendingId) updatePendingGrowthWrite(pendingId, { status: 'failed' });
      return { ok: false, error: collected.error };
    }
    onStage({
      event_type: collected.evidenceRecords.length ? 'EVIDENCE_READY' : 'EVIDENCE_REFS_ONLY',
      summary: collected.evidenceRecords.length
        ? `Evidence Ledger 已透传 ${collected.evidenceRecords.length} 条证据`
        : `Evidence 详情暂不可读，保留 ${collected.evidenceRefs.length} 个证据引用`,
      sender: 'evidence_review_agent',
      receiver: 'growth_state',
      payload: {
        records: collected.evidenceRecords.map((record) => ({
          evidence_id: record?.evidence_id,
          candidate_id: record?.candidate_id,
          source_type: record?.source_type,
          source_uri: record?.source_uri,
          title: record?.title,
          freshness: record?.freshness,
          extracted_fact: typeof record?.extracted_fact === 'string'
            ? record.extracted_fact.slice(0, 300)
            : undefined,
        })),
      },
      evidence_refs: collected.evidenceRefs,
    });
    if (collected.reviewStatus === 'NO_MATCH') {
      onStage({
        event_type: 'NO_QUALIFIED_MATCH',
        summary: '严格条件下暂无可核验导师；已提供可放宽项与候选归零诊断。',
        sender: 'result_composer_agent',
        receiver: 'api',
        payload: collected.noMatchDiagnostics,
        evidence_refs: collected.evidenceRefs,
      });
    }
    const identity = isNumericRunId(runId) ? runId : '';
    if (Number.isFinite(userId)) {
      try {
        if (!identity) {
          throw new Error('缺少数值 AgentRun id，拒绝把 trace_id 写入成长状态');
        }
        commitMentorPass(userId, identity, traceId, message, collected);
        if (pendingId) updatePendingGrowthWrite(pendingId, { status: 'written', runId: identity });
      } catch (err) {
        if (pendingId) {
          updatePendingGrowthWrite(pendingId, {
            status: 'pending_reconcile',
            runId: identity || null,
            lastError: err instanceof Error ? err.message : '成长写回失败',
          });
        }
      }
    }
    const trustedGrowth = Number.isFinite(userId)
      ? (loadTrustedAgentContext(userId).growth as Record<string, unknown>)
      : ((context.growth || {}) as Record<string, unknown>);
    return {
      ok: true,
      advisors: collected.advisors,
      run_id: identity,
      trace_id: traceId,
      review_status: collected.reviewStatus,
      evidence_refs: collected.evidenceRefs,
      evidence_records: collected.evidenceRecords,
      query_contract: collected.queryContract,
      retrieval_attempts: collected.retrievalAttempts,
      relation_judgements: collected.relationJudgements,
      coverage_report: collected.coverageReport,
      no_match_diagnostics: collected.noMatchDiagnostics,
      summary: collected.reviewStatus === 'NO_MATCH'
        ? '严格条件下暂无可核验导师；已返回可放宽条件与检索诊断。'
        : `为你找到 ${collected.advisors.length} 位匹配导师。审核与返工过程已记入本轮 Agent 活动。`,
      suggested_next_skill: suggestNextSkill(trustedGrowth),
    };
  } catch (err: any) {
    return { ok: false, error: err?.message || '代理调用 A 后端异常' };
  }
}

function shouldUsePlainConversation(message: string): boolean {
  const text = message.trim().toLowerCase();
  if (!text) return false;
  return /^(你好|您好|嗨|哈喽|hello|hi|hey|谢谢|多谢|再见|晚安|早上好|下午好|晚上好)[!！。,.， ]*$/.test(text)
    || /(先聊聊|聊聊天|简单说|通俗一点|别检索|不要检索|暂停这个目标|换个目标|改一下目标|回到之前的目标)/.test(text);
}

async function proxyToPaperClawChat(
  userId: number,
  message: string,
  emitText: (text: string) => void,
  isCancelled: () => boolean,
): Promise<{ ok: true; text: string } | { ok: false; error: string }> {
  if (!agentBase()) return { ok: false, error: 'PAPERCLAW Agent 未配置' };
  if (!await probeAgent(1500)) return { ok: false, error: 'PAPERCLAW Agent 当前未就绪（数据库或上游依赖不可用）' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), agentTimeoutMs());
  try {
    const userLlm = getLlmApiSettings(userId, true);
    const userModelOverrides = userLlm.enabled && userLlm.baseUrl && userLlm.model && userLlm.apiKey
      ? { model: userLlm.model, api_key: userLlm.apiKey, base_url: userLlm.baseUrl }
      : {};
    const upstream = await fetch(agentUrl('/api/agent/messages/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        ...userModelOverrides,
        metadata: { surface: 'search', owner_id: String(userId) },
      }),
      signal: controller.signal,
    });
    if (!upstream.ok || !upstream.body) return { ok: false, error: `PAPERCLAW Agent 调用失败（HTTP ${upstream.status}）` };
    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalText = '';
    let streamed = false;
    const consume = (line: string) => {
      if (!line.trim()) return;
      try {
        const event = JSON.parse(line) as { type?: string; message?: string; error?: string };
        if (event.type === 'agent_chunk' && event.message) { streamed = true; emitText(event.message); }
        if (event.type === 'run_completed' && event.message) finalText = event.message;
        if (event.type === 'run_failed' && event.error) finalText = `这次处理没有完成：${event.error}`;
      } catch { /* 忽略无法解析的中间行 */ }
    };
    while (!isCancelled()) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      lines.forEach(consume);
    }
    buffer += decoder.decode();
    consume(buffer);
    if (finalText && !streamed) emitText(finalText);
    return finalText ? { ok: true, text: finalText } : { ok: true, text: '' };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'PAPERCLAW Agent 调用失败' };
  } finally {
    clearTimeout(timer);
  }
}

agentRouter.post('/chat', (req: AuthRequest, res: Response) => {
  const { message, resume_trace_id, upload_id } = req.body ?? {};
  if (!message || typeof message !== 'string') {
    res.status(400).json({ message: '请提供 message 字段' });
    return;
  }

  res.status(200)
    .set({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    })
    .flushHeaders();

  const aborted = { cancelled: false };
  req.on('aborted', () => {
    aborted.cancelled = true;
    res.end();
  });

  const userId = req.userId!;
  let missionId: number | null = null;
  let seq = 0;

  const emitEvent = (ev: RuntimeEvent): void => {
    if (aborted.cancelled) return;
    const staged: RuntimeEvent = {
      ...ev,
      stage: ev.stage || inferStageFromEvent(ev.event_type, ev.sender),
    };
    sse(res, 'event', { type: 'event', event: staged });
    const hint = EVENT_HINT[staged.event_type];
    if (hint) {
      sse(res, 'thinking', { type: 'thinking', content: hint });
    }
    seq += 1;
    persistEvent(missionId, seq, staged);
  };

  (async () => {
    if (!resume_trace_id && shouldUsePlainConversation(message)) {
      sse(res, 'thinking', { type: 'thinking', content: '先正常聊聊，不启动导师检索。' });
      const plain = await proxyToPaperClawChat(userId, message, (text) => {
        if (!aborted.cancelled && text) sse(res, 'summary', { type: 'summary', content: text });
      }, () => aborted.cancelled);
      if (aborted.cancelled) return;
      if (!plain.ok) {
        sse(res, 'error', { type: 'error', code: 'PAPERCLAW_CHAT_FAILED', message: plain.error });
      } else {
        sse(res, 'result', { type: 'result', response_kind: 'chat', advisors: [] });
        sse(res, 'done', { type: 'done', response_kind: 'chat' });
      }
      res.end();
      return;
    }
    const uploadId = typeof upload_id === 'string' && upload_id.trim() ? upload_id.trim() : null;
    const parsedDocs = uploadId ? await buildParsedDocuments(uploadId, userId) : [];

    if (agentBase() && await probeAgent(2500)) {
      const trusted = loadTrustedAgentContext(userId);
      const resumeTraceId = typeof resume_trace_id === 'string' && resume_trace_id.trim()
        ? resume_trace_id.trim()
        : undefined;
      missionId = createMission(
        userId,
        resumeTraceId || `harness_${Date.now().toString(36)}`,
        message,
        'mentor_agent',
      );

      emitEvent({
        event_type: resumeTraceId ? 'WORKFLOW_RESUMED' : 'WORKFLOW_CREATED',
        stage: 'input_understanding',
        sender: 'workflow_orchestrator',
        receiver: 'input_understanding_agent',
        message: resumeTraceId ? 'Harness 正在续跑同一轮 Mentor Skill' : 'Harness 已启动 Mentor Skill',
      });
      sse(res, 'stage', {
        type: 'stage',
        event_type: resumeTraceId ? 'WORKFLOW_RESUMED' : 'WORKFLOW_CREATED',
        summary: resumeTraceId ? 'Harness 正在续跑同一轮 Mentor Skill' : 'Harness 已启动 Mentor Skill',
        sender: 'workflow_orchestrator',
      });

      const result = await proxyToMentorAgent(
        message,
        { user_id: String(userId), growth: trusted.growth, profile: trusted.profile, parsed_documents: parsedDocs },
        (payload) => {
          if (aborted.cancelled) return;
          if (SILENCED_A_EVENTS.has(payload.event_type)) return;
          const safePayload = stripResultFields(
            payload.payload && typeof payload.payload === 'object'
              ? payload.payload as Record<string, unknown>
              : undefined,
          );
          sse(res, 'stage', { type: 'stage', ...payload, payload: safePayload });
          emitEvent({
            event_type: payload.event_type,
            stage: inferStageFromEvent(payload.event_type, payload.sender),
            sender: payload.sender,
            receiver: payload.receiver,
            timestamp: payload.timestamp,
            payload: safePayload,
            evidence_refs: payload.evidence_refs,
            message: payload.summary,
          });
        },
        () => aborted.cancelled,
        resumeTraceId,
      );

      if (aborted.cancelled) return;

      if (result.ok) {
        if ('clarification' in result) {
          emitEvent({
            event_type: 'CLARIFICATION_REQUIRED',
            stage: 'input_understanding',
            payload: { questions: result.clarification },
            sender: 'input_understanding_agent',
            receiver: 'workflow_orchestrator',
            message: '需要补充信息',
          });
          const questions = result.clarification.filter((q) => q.trim().length > 0);
          const content = questions.length
            ? `需要补充一点信息才能继续：\n${questions.map((q) => `· ${q}`).join('\n')}`
            : '需要补充一点信息才能继续，请换个更具体的研究方向。';
          sse(res, 'summary', {
            type: 'summary',
            content,
            trace_id: result.trace_id,
            run_id: result.run_id,
            clarification_pending: true,
          });
          sse(res, 'done', {
            type: 'done',
            trace_id: result.trace_id,
            run_id: result.run_id,
            clarification_pending: true,
          });
          res.end();
          return;
        }

        // A is the single retrieval authority when it is available.  Do not
        // re-run D's legacy keyword scorer here: it could produce a different
        // candidate/evidence set from the reviewed HARNESS result.
        const advisors = keepDisplayableAdvisors(result.advisors || []);
        const noMatch = result.review_status === 'NO_MATCH' || advisors.length === 0;
        const summary = noMatch
          ? '没有达到相关阈值的导师'
          : `找到 ${advisors.length} 位达到相关阈值的导师。`;
        finalizeMission(missionId, noMatch ? 'NO_MATCH' : 'COMPLETED', advisors.map((a: any) => a.id).filter(Boolean));

        const harnessLedger = mapHarnessEvidenceLedger([], advisors);

        if (advisors.length && isNumericRunId(result.run_id)) {
          sse(res, 'stage', {
            type: 'stage',
            event_type: 'GROWTH_STATE_UPDATED',
            summary: 'Review 结果已写回科研成长状态',
            evidence_refs: advisors.flatMap((a: any) => a.evidenceRefs ?? []),
          });
        }
        const reviewStatus = noMatch ? 'NO_MATCH' : (result.review_status || 'PASS');
        emitEvent({
          event_type: noMatch || reviewStatus !== 'PASS' ? 'REVIEW_FAILED' : 'REVIEW_PASSED',
          stage: 'evidence_review',
          sender: 'evidence_review_agent',
          receiver: 'result_composer_agent',
          payload: {
            status: reviewStatus,
            failed_checks: noMatch ? ['no_qualified_match'] : [],
            no_match: noMatch,
            reviewer_summary: summary,
          },
        });
        emitEvent({
          event_type: 'WORKFLOW_COMPLETED',
          stage: noMatch ? 'failed' : 'completed',
          sender: 'workflow_orchestrator',
          receiver: 'api',
          payload: {
            quality_status: noMatch ? 'NO_MATCH' : 'PASS',
            mentor_count: advisors.length,
            query_contract: result.query_contract,
            retrieval_attempts: result.retrieval_attempts,
            relation_judgements: result.relation_judgements,
            coverage_report: result.coverage_report,
            no_match_diagnostics: result.no_match_diagnostics,
            review_decision: {
              status: reviewStatus,
              reviewer_summary: summary,
              reviewed_candidate_ids: advisors.map((a: any) => a.id),
              failed_checks: noMatch ? ['no_qualified_match'] : [],
            },
            evidence_ledger: harnessLedger,
            match_results: advisors.map((a: any, idx: number) => ({
              candidate_id: a.id,
              total_score: a.matchScore,
              ranking_position: idx + 1,
              match_type: a.matchType,
              score_breakdown: a.scoreBreakdown,
              rationale: a.explanation ? [a.explanation] : [],
            })),
            task_plan: {
              steps: [
                { step_id: 'mentor_research', agent_name: 'mentor_research_agent' },
                { step_id: 'matching', agent_name: 'matching_agent' },
                { step_id: 'evidence_review', agent_name: 'evidence_review_agent' },
                { step_id: 'result_composer', agent_name: 'result_composer_agent' },
              ],
            },
          },
          evidence_refs: advisors.flatMap((a: any) => a.evidenceRefs ?? []),
        });

        sse(res, 'result', {
          type: 'result',
          advisors,
          run_id: result.run_id,
          trace_id: result.trace_id,
          threshold: relevanceThreshold(),
          review_status: reviewStatus,
          evidence_refs: advisors.flatMap((a: any) => a.evidenceRefs ?? []),
          no_match_diagnostics: noMatch ? result.no_match_diagnostics : undefined,
          suggested_next_skill: advisors.length ? result.suggested_next_skill : null,
          clarification_pending: false,
        });
        sse(res, 'summary', { type: 'summary', content: summary });
        sse(res, 'done', { type: 'done', trace_id: result.trace_id, run_id: result.run_id });
        res.end();
        return;
      }

      const timedOut = /耗时较长|超时/.test(String(result.error || ''));
      sse(res, 'thinking', {
        type: 'thinking',
        content: timedOut
          ? 'A 端检索耗时较长，正在使用同一查询切换本地语义检索…'
          : 'A 端检索服务暂不可用，正在使用同一查询切换本地语义检索…',
      });
    } else {
      sse(res, 'thinking', { type: 'thinking', content: agentBase()
        ? 'A 端当前未就绪，正在使用同一查询切换本地语义检索…'
        : '正在通过本地导师库分析你的需求…' });
    }

    if (ragData.isReady) {
      await runLocalRag(message, res, aborted, userId, (id) => { missionId = id; }, emitEvent);
      return;
    }

    sse(res, 'error', {
      type: 'error',
      message: '导师数据源不可用，且未配置 MENTOR_AGENT_BASE_URL。请确认 RAG 数据已生成或启动 A 端。',
    });
    res.end();
  })().catch((err) => {
    if (aborted.cancelled) return;
    sse(res, 'error', { type: 'error', message: err?.message || '内部错误' });
    res.end();
  });
});

agentRouter.post('/read', async (req: AuthRequest, res: Response) => {
  const { candidate_id, paper_id } = req.body ?? {};
  if (!candidate_id || typeof candidate_id !== 'string') {
    res.status(400).json({ message: '请提供 candidate_id' });
    return;
  }
  try {
    const result = await runHarnessSkill({
      userId: req.userId!,
      skillId: 'paper_qa',
      message: `阅读导师 ${candidate_id} 的论文与项目`,
      query: candidate_id,
      context: {
        candidate_id,
        paper_id: typeof paper_id === 'number' ? paper_id : Number(paper_id) || undefined,
      },
      patcher: (runId, payload) => paperGrowthPatch(runId, candidate_id, payload),
    });
    res.json(result);
  } catch (err: any) {
    res.status(err?.status || 502).json({ message: err?.message || '无法连接 Paper Skill' });
  }
});

function decodeUploadName(name: string): string {
  if (!name) return name;
  try {
    const repaired = Buffer.from(name, 'latin1').toString('utf8');
    const repairedHasCjk = /[\u4e00-\u9fff]/.test(repaired);
    const originalHasCjk = /[\u4e00-\u9fff]/.test(name);
    if (repairedHasCjk && !originalHasCjk) return repaired;
  } catch {
    /* keep original */
  }
  return name;
}

const paperUpload = multer({
  storage: multer.diskStorage({
    destination: (_req, _file, cb) => cb(null, os.tmpdir()),
    filename: (_req, file, cb) => {
      file.originalname = decodeUploadName(file.originalname);
      const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
      cb(null, `paper-${unique}${path.extname(file.originalname) || '.pdf'}`);
    },
  }),
  limits: { fileSize: 20 * 1024 * 1024 },
  defParamCharset: 'utf8',
});

agentRouter.post('/paper-upload', paperUpload.single('file'), async (req: AuthRequest, res: Response) => {
  const file = req.file;
  const candidateId = String(req.body?.candidate_id || '');
  const previousRunId = String(req.body?.run_id || '');
  if (!file) {
    res.status(400).json({ message: '未收到 PDF 文件' });
    return;
  }
  if (!candidateId) {
    await fs.promises.unlink(file.path).catch(() => {});
    res.status(400).json({ message: '请提供 candidate_id' });
    return;
  }
  if (!agentBase()) {
    await fs.promises.unlink(file.path).catch(() => {});
    res.status(503).json({ message: '未配置 MENTOR_AGENT_BASE_URL' });
    return;
  }
  try {
    const doc = persistUploadedPdf({
      userId: req.userId!,
      originalName: file.originalname,
      sourcePath: file.path,
    });
    const pages = await extractPdfPages(doc.storedPath);
    if (!pages.length) {
      res.status(409).json({
        message: '未能抽出可检索正文（扫描件或图片 PDF），无法入库，也不会按文件名推荐导师。',
        document_id: doc.documentId,
        review_status: 'NEED_MORE_INPUT',
      });
      return;
    }
    let paperId = Number(req.body?.paper_id || 0);
    if (!Number.isFinite(paperId) || paperId <= 0) {
      const created = await postHarnessRun({
        skill_id: 'paper_qa',
        message: `为导师 ${candidateId} 准备论文入库`,
        context: {
          user_id: String(req.userId!),
          candidate_id: candidateId,
          growth: loadTrustedAgentContext(req.userId!).growth,
        },
      });
      paperId = Number(created?.artifact?.paper_id || 0);
    }
    if (!Number.isFinite(paperId) || paperId <= 0) {
      res.status(502).json({ message: '无法解析对应的 paper_id' });
      return;
    }
    const form = new FormData();
    form.append('role', 'pdf');
    if (isNumericRunId(previousRunId)) form.append('run_id', previousRunId);
    form.append(
      'file',
      new Blob([fs.readFileSync(doc.storedPath)], { type: 'application/pdf' }),
      file.originalname || 'paper.pdf',
    );
    const uploadRes = await fetch(agentUrl(`/api/papers/${paperId}/artifacts/upload`), {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(agentTimeoutMs()),
    });
    const uploaded: any = uploadRes.ok ? await uploadRes.json().catch(() => ({})) : {};
    const ingestRes = await fetch(agentUrl(`/api/papers/${paperId}/page-ingest`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pages,
        run_id: isNumericRunId(previousRunId) ? Number(previousRunId) : undefined,
        artifact_id: uploaded?.id,
      }),
      signal: AbortSignal.timeout(agentTimeoutMs()),
    });
    if (!ingestRes.ok) {
      const txt = await ingestRes.text().catch(() => '');
      res.status(ingestRes.status).json({ message: txt.slice(0, 300) || '论文页级入库失败' });
      return;
    }
    const ingest = await ingestRes.json();
    saveRunArtifact({
      userId: req.userId!,
      runId: previousRunId && isNumericRunId(previousRunId) ? previousRunId : `paper-upload:${paperId}`,
      skillId: 'paper_upload',
      query: candidateId,
      reviewStatus: 'PASS',
      payload: { paper_id: paperId, document_id: doc.documentId, ingest, pages: pages.length },
    });
    res.json({
      paper_id: paperId,
      document_id: doc.documentId,
      chunk_ids: ingest.chunk_ids,
      page_count: ingest.page_count,
      retry: { skill_id: 'paper_qa', paper_id: paperId, candidate_id: candidateId },
    });
  } catch (err: any) {
    res.status(err?.status || 502).json({ message: err?.message || '论文上传入库失败' });
  } finally {
    if (file?.path) await fs.promises.unlink(file.path).catch(() => {});
  }
});

agentRouter.get('/artifacts', (req: AuthRequest, res: Response) => {
  const advisorId = typeof req.query.advisor_id === 'string' ? req.query.advisor_id : undefined;
  const skillId = typeof req.query.skill_id === 'string' ? req.query.skill_id : undefined;
  res.json(listRunArtifacts(req.userId!, { advisorId, skillId }));
});

agentRouter.get('/artifacts/:runId', (req: AuthRequest, res: Response) => {
  const row = loadRunArtifactByRunId(req.userId!, req.params.runId);
  if (!row) {
    res.status(404).json({ message: '未找到该运行产物' });
    return;
  }
  res.json(row);
});

const LOCAL_RAG_LIMIT = 5;

function matchesToAdvisors(
  retrieval: ReturnType<typeof retrieveQualifiedMentors>,
  fallback: boolean,
) {
  return keepDisplayableAdvisors(retrieval.matches.map((match) => ({
    ...toLightAdvisor(match.candidate),
    matchScore: Math.round(match.finalScore),
    scoreKind: fallback ? 'calibrated_relevance_fallback' : 'calibrated_relevance',
    matchType: match.matchType,
    scoreBreakdown: match.scoreBreakdown,
    queryContract: retrieval.query,
    retrievalConfidence: fallback ? 0.82 : 1,
    evidenceConfidence: match.scoreBreakdown.evidence_confidence / 100,
    evidenceRefs: match.evidence.map((item) => item.evidence_id),
    evidence: match.evidence,
    explanation: [
      match.matchType === 'DIRECT' ? '官方研究方向精确支持该查询。' : '同一语义边界内的邻近主题支持该查询。',
      fallback ? '远程检索失败，本地回退使用同一查询并已降低置信度。' : '',
      '分数是校准后的主题相关分，不是匹配成功概率。',
    ].filter(Boolean).join(''),
  })));
}

function qualifyFromLocalRag(query: string, fallback: boolean) {
  if (!ragData.isReady) {
    const retrieval = retrieveQualifiedMentors(query, [], () => [], { fallback, limit: LOCAL_RAG_LIMIT });
    return { retrieval, advisors: [] as ReturnType<typeof matchesToAdvisors>, review: reviewMatches(retrieval.query, []) };
  }
  const retrieval = retrieveQualifiedMentors(
    query,
    ragStore.getCandidates(),
    (candidateId) => ragStore.getEvidenceFor(candidateId),
    { fallback, limit: LOCAL_RAG_LIMIT },
  );
  const advisors = matchesToAdvisors(retrieval, fallback);
  return { retrieval, advisors, review: reviewMatches(retrieval.query, retrieval.matches) };
}

async function runLocalRag(
  message: string,
  res: Response,
  aborted: { cancelled: boolean },
  userId: number,
  setMissionId: (id: number | null) => void,
  emitEvent: (ev: RuntimeEvent) => void,
): Promise<void> {
  const traceId = `local_${Date.now().toString(36)}`;
  const missionId = createMission(userId, traceId, message, 'local_rag');
  setMissionId(missionId);

  const candidates = ragStore.getCandidates();
  const fallback = Boolean(agentBase());
  const { retrieval, advisors, review } = qualifyFromLocalRag(message, fallback);
  const noMatch = review.no_match || advisors.length === 0;
  const summary = noMatch ? '没有达到相关阈值的导师' : review.reviewer_summary;

  const advisorIds = advisors.map((a) => a.id);
  const evidenceLedger = retrieval.matches.flatMap((match) => match.evidence);
  const planSteps = [
    { step_id: 'domain_analysis', agent_name: 'domain_expert_agent' },
    { step_id: 'mentor_research', agent_name: 'mentor_research_agent' },
    { step_id: 'matching', agent_name: 'matching_agent' },
    { step_id: 'evidence_review', agent_name: 'evidence_review_agent' },
    { step_id: 'result_composer', agent_name: 'result_composer_agent' },
  ];

  const beat = async (ev: RuntimeEvent, waitMs = 220): Promise<boolean> => {
    if (aborted.cancelled) return false;
    emitEvent(ev);
    await sleep(waitMs);
    return !aborted.cancelled;
  };

  if (!await beat({ event_type: 'WORKFLOW_CREATED', stage: 'input_understanding', sender: 'workflow_orchestrator', receiver: 'input_understanding_agent', payload: { message, source: 'local_rag' } })) return;
  if (!await beat({ event_type: 'INPUT_RECEIVED', stage: 'input_understanding', sender: 'input_understanding_agent', receiver: 'planning_agent', payload: { message } })) return;
  if (!await beat({ event_type: 'INTENT_READY', stage: 'input_understanding', sender: 'input_understanding_agent', receiver: 'planning_agent', payload: { query_contract: retrieval.query } })) return;
  if (!await beat({ event_type: 'PLAN_READY', stage: 'planning', sender: 'planning_agent', receiver: 'workflow_orchestrator', payload: { steps: planSteps } })) return;
  if (!await beat({ event_type: 'DOMAIN_ANALYSIS_STARTED', stage: 'domain_expert', sender: 'domain_expert_agent', receiver: 'mentor_research_agent' })) return;
  if (!await beat({ event_type: 'DOMAIN_ANALYSIS_READY', stage: 'domain_expert', sender: 'domain_expert_agent', receiver: 'mentor_research_agent' })) return;
  if (!await beat({ event_type: 'RESEARCH_STARTED', stage: 'mentor_research', sender: 'mentor_research_agent', receiver: 'matching_agent' })) return;
  if (!await beat({ event_type: 'RESEARCH_DONE', stage: 'mentor_research', sender: 'mentor_research_agent', receiver: 'matching_agent', payload: { scanned_count: candidates.length, qualified_count: advisors.length }, evidence_refs: evidenceLedger.map((e: any) => e.evidence_id) })) return;
  if (!await beat({ event_type: 'MATCHING_STARTED', stage: 'matching', sender: 'matching_agent', receiver: 'evidence_review_agent' })) return;
  if (!await beat({ event_type: 'MATCHING_DONE', stage: 'matching', sender: 'matching_agent', receiver: 'evidence_review_agent', payload: { match_count: advisors.length, threshold: relevanceThreshold() } })) return;
  if (!await beat({ event_type: 'REVIEW_STARTED', stage: 'evidence_review', sender: 'evidence_review_agent', receiver: 'result_composer_agent' })) return;
  if (!await beat({
    event_type: review.status === 'PASS' && !noMatch ? 'REVIEW_PASSED' : 'REVIEW_FAILED',
    stage: 'evidence_review',
    sender: 'evidence_review_agent',
    receiver: 'result_composer_agent',
    payload: {
      status: noMatch ? 'NO_MATCH' : review.status,
      failed_checks: noMatch ? ['no_qualified_match'] : review.failed_checks,
      no_match: noMatch,
      reviewer_summary: review.reviewer_summary,
    },
  })) return;
  if (!await beat({ event_type: 'COMPOSING_RESULT', stage: 'result_composer', sender: 'result_composer_agent', receiver: 'workflow_orchestrator' })) return;

  if (aborted.cancelled) return;
  sse(res, 'result', {
    type: 'result',
    advisors,
    query: retrieval.query,
    threshold: relevanceThreshold(),
    review_status: noMatch ? 'NO_MATCH' : review.status,
  });
  sse(res, 'summary', { type: 'summary', content: summary });
  finalizeMission(missionId, noMatch ? 'NO_MATCH' : 'COMPLETED', advisorIds);
  emitEvent({
    event_type: 'WORKFLOW_COMPLETED',
    stage: noMatch ? 'failed' : 'completed',
    sender: 'workflow_orchestrator',
    receiver: 'api',
    payload: {
      quality_status: noMatch ? 'NO_MATCH' : 'PASS',
      mentor_count: advisors.length,
      query: retrieval.query,
      review_decision: {
        status: noMatch ? 'NO_MATCH' : review.status,
        reviewer_summary: summary,
        failed_checks: noMatch ? ['no_qualified_match'] : review.failed_checks,
      },
      evidence_ledger: evidenceLedger.filter((item: any) =>
        item?.support_type === 'DIRECT' || item?.support_type === 'ADJACENT',
      ),
      match_results: advisors.map((a, idx) => ({
        candidate_id: a.id,
        total_score: a.matchScore,
        ranking_position: idx + 1,
        match_type: a.matchType,
        score_breakdown: a.scoreBreakdown,
        evidence_refs: a.evidenceRefs,
        rationale: [a.explanation],
      })),
      task_plan: { steps: planSteps },
    },
  });
  sse(res, 'done', { type: 'done', trace_id: traceId });
  res.end();
}

let reconciling = false;

export async function reconcilePendingGrowthWrites(): Promise<void> {
  if (!agentBase() || reconciling) return;
  reconciling = true;
  try {
    const rows = listPendingGrowthWrites(['polling', 'pending_reconcile']);
    for (const row of rows) {
      if (row.attemptCount >= 8) {
        updatePendingGrowthWrite(row.id, { status: 'dead', lastError: '超过重试次数' });
        continue;
      }
      updatePendingGrowthWrite(row.id, { lock: true, bumpAttempt: true });
      try {
        if (row.skillId === 'mentor_match' && row.traceId) {
          const stRes = await fetch(
            agentUrl(`/api/mentor-workflows/${encodeURIComponent(row.traceId)}/status`),
            { signal: AbortSignal.timeout(8000) },
          );
          if (!stRes.ok) continue;
          const st: any = await stRes.json();
          const status = String(st?.status || '');
          if (status === 'CLARIFICATION_REQUIRED') {
            updatePendingGrowthWrite(row.id, { status: 'waiting_input' });
            continue;
          }
          if (status === 'FAILED') {
            updatePendingGrowthWrite(row.id, { status: 'failed' });
            continue;
          }
          if (status !== 'COMPLETED') continue;
          const collected = await collectMentorResult(row.traceId);
          if ('error' in collected) {
            updatePendingGrowthWrite(row.id, { status: 'failed', lastError: collected.error });
            continue;
          }
          if (!isNumericRunId(row.runId)) {
            updatePendingGrowthWrite(row.id, {
              status: 'pending_reconcile',
              lastError: '缺少数值 AgentRun id，拒绝把 trace_id 写入成长状态',
            });
            continue;
          }
          commitMentorPass(row.userId, row.runId, row.traceId, row.query || '', collected);
          updatePendingGrowthWrite(row.id, { status: 'written', runId: row.runId });
          continue;
        }
        if (row.runId && isNumericRunId(row.runId)) {
          const resultRes = await fetch(agentUrl(`/api/runs/${row.runId}/harness-result`), {
            signal: AbortSignal.timeout(8000),
          });
          if (!resultRes.ok) continue;
          const result: any = await resultRes.json();
          const status = String(result?.status || '');
          if (!['succeeded', 'failed', 'cancelled', 'waiting_for_user'].includes(status)) continue;
          if (row.skillId === 'progress_report') {
            if (reconcileProgressReport(row.userId, row.payload, result)) {
              updatePendingGrowthWrite(row.id, { status: 'written', runId: row.runId });
            } else {
              updatePendingGrowthWrite(row.id, {
                status: status === 'waiting_for_user' ? 'waiting_input' : 'failed',
                lastError: result?.artifact?.error || `报告任务状态：${status}`,
              });
            }
            continue;
          }
          if (result?.review_status === 'PASS') {
            const patcher = row.skillId === 'paper_qa'
              ? paperGrowthPatch(row.runId, String(row.payload.candidate_id || row.query || ''), result)
              : row.skillId === 'pdf_analyze'
                ? pdfGrowthPatch(row.runId, String(row.payload.document_id || row.query || ''), result)
                : row.skillId === 'email_compose'
                  ? emailGrowthPatch(row.runId, String(row.payload.candidate_id || row.query || ''), result)
                  : null;
            if (!patcher) {
              updatePendingGrowthWrite(row.id, { status: 'failed', lastError: `未知 skill ${row.skillId}` });
              continue;
            }
            commitHarnessPass({
              userId: row.userId,
              runId: row.runId,
              skillId: row.skillId,
              query: row.query || '',
              result,
              patch: patcher,
              pendingId: row.id,
              traceId: row.traceId,
            });
          } else {
            updatePendingGrowthWrite(row.id, {
              status: status === 'waiting_for_user' ? 'waiting_input' : 'failed',
            });
          }
        }
      } catch (err) {
        updatePendingGrowthWrite(row.id, {
          status: 'pending_reconcile',
          lastError: err instanceof Error ? err.message : 'reconcile failed',
        });
      }
    }
  } finally {
    reconciling = false;
  }
}

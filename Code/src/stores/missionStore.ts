import { create } from 'zustand';
import type { RuntimeEvent, WorkflowStage } from '../types/search';
import { inferEventStage } from '../utils/workflowStage';

/**
 * Mission 工作区状态（D_PLAN §5.3）。
 *
 * 承载一次检索的结构化运行态：当前阶段、Plan、复核决定、证据账本、匹配结果、
 * 运行时事件流。数据来源是后端 SSE 的 `event` 事件（agent.ts 发的 RuntimeEvent，
 * 其中 WORKFLOW_COMPLETED 事件 payload 内含 review_decision/evidence_ledger/match_results/task_plan）。
 *
 * 与 searchStore 分离：searchStore 管「对话/检索结果」，missionStore 管「Mission 工作流态」，
 * 避免把 searchStore 撑得过大；两者在同一轮检索里协同更新。
 */

/** A 的 8 维匹配分项（MatchDimensionScores，schemas.py:323-331） */
export interface DimensionScores {
  research_topic_match?: number;
  method_match?: number;
  application_match?: number;
  recent_activity?: number;
  student_background_fit?: number;
  constraint_satisfaction?: number;
  recruitment_fit?: number;
  evidence_completeness?: number;
  [key: string]: number | undefined;
}

/** A 的复核决定（ReviewDecision，schemas.py:360-369） */
export interface ReviewDecision {
  review_id?: string;
  status?: string; // PASS / REVISE / RESEARCH_AGAIN / NEED_MORE_INPUT / FAILED
  reviewed_candidate_ids?: string[];
  failed_checks?: string[];
  revision_target?: string | null;
  revision_reason?: string | null;
  reviewer_summary?: string;
}

/** A 的证据记录（EvidenceRecord，schemas.py:281-303） */
export interface EvidenceRecord {
  evidence_id?: string;
  candidate_id?: string | null;
  source_type?: string;
  source_uri?: string;
  title?: string;
  extracted_fact?: string;
  locator?: string;
  retrieved_at?: string;
  freshness?: string; // current / recent / stale / unknown
  confidence?: number;
  query_relevance?: number;
  entity_verified?: boolean;
  support_type?: string;
  source_level?: string;
  query?: string;
}

/** A 的匹配结果（MatchResult，schemas.py:338-347） */
export interface MatchResult {
  candidate_id?: string;
  total_score?: number;
  match_type?: string;
  dimension_scores?: DimensionScores;
  rationale?: string[];
  ranking_position?: number;
}

/** A 的 TaskPlan（schemas.py:254-264） */
export interface TaskPlan {
  steps?: Array<{ step_id?: string; agent_name?: string; enabled?: boolean }>;
  skipped_steps?: string[];
  execution_mode?: string;
}

interface MissionState {
  /** 当前工作流阶段（从事件 stage 推进） */
  currentStage: WorkflowStage | null;
  /** 当前正在工作的 agent（取最新事件 sender） */
  currentAgent: string | null;
  /** 是否运行中 */
  running: boolean;
  /** 运行时事件流（用于右侧 Timeline 区，与 chatHistory 内 events 同步） */
  events: RuntimeEvent[];
  /** Plan 区数据 */
  plan: TaskPlan | null;
  /** 复核决定（Review 区） */
  reviewDecision: ReviewDecision | null;
  /** 证据账本（Evidence 区） */
  evidenceLedger: EvidenceRecord[];
  /** 匹配结果（含 8 维分项，供卡片/对比用） */
  matchResults: MatchResult[];
  /** 合格结果质量：无匹配时审核/编排不得显示为成功完成 */
  qualityStatus: string | null;
  /** 触发重试次数（取 TASK_RETRY payload.retry_count 最大值） */
  retryCount: number;

  /** 接收一条运行时事件，更新工作流态 */
  ingestEvent: (ev: RuntimeEvent) => void;
  /** 开始新一轮检索前重置（保留历史由 chatHistory 承载） */
  reset: () => void;
}

const QUALIFIED_SCORE_FLOOR = 60;

function queryBoundEvidence(records: EvidenceRecord[]): EvidenceRecord[] {
  return records.filter((item) =>
    Boolean(item.candidate_id)
    && (item.support_type === 'DIRECT' || item.support_type === 'ADJACENT')
    && item.source_level !== 'L5'
    && Number(item.query_relevance ?? 1) > 0,
  );
}

function qualifiedMatchResults(matches: MatchResult[]): MatchResult[] {
  return matches.filter((item) =>
    Number(item.total_score) >= QUALIFIED_SCORE_FLOOR
    && item.match_type !== 'UNASSESSED'
    && item.match_type !== 'UNRELATED',
  );
}

const initial = {
  currentStage: null,
  currentAgent: null,
  running: false,
  events: [],
  plan: null,
  reviewDecision: null,
  evidenceLedger: [],
  matchResults: [],
  qualityStatus: null,
  retryCount: 0,
};

export const useMissionStore = create<MissionState>((set) => ({
  ...initial,

  ingestEvent: (ev) => {
    set((state) => {
      const next: Partial<MissionState> = {
        events: [...state.events, ev],
      };
      const inferred = inferEventStage(ev);
      if (inferred) next.currentStage = inferred;
      if (ev.sender) next.currentAgent = ev.sender;
      next.running = !['WORKFLOW_COMPLETED', 'WORKFLOW_FAILED'].includes(ev.event_type);

      // PLAN_READY / state 事件带 task_plan
      if (ev.event_type === 'PLAN_READY' && ev.payload?.steps) {
        next.plan = { steps: ev.payload.steps as TaskPlan['steps'], skipped_steps: ev.payload?.skipped_steps as string[] | undefined, execution_mode: undefined };
      }
      // WORKFLOW_COMPLETED（含全状态）：payload 内嵌 review/evidence/matches/task_plan
      if (ev.event_type === 'WORKFLOW_COMPLETED' && ev.payload) {
        const p = ev.payload;
        if (p.task_plan) next.plan = p.task_plan as TaskPlan;
        if (p.review_decision) next.reviewDecision = p.review_decision as ReviewDecision;
        const quality = String(p.quality_status || (p.review_decision as ReviewDecision | undefined)?.status || '');
        if (quality) next.qualityStatus = quality;
        if (Array.isArray(p.evidence_ledger)) next.evidenceLedger = queryBoundEvidence(p.evidence_ledger as EvidenceRecord[]);
        if (Array.isArray(p.match_results)) next.matchResults = qualifiedMatchResults(p.match_results as MatchResult[]);
        if (quality === 'NO_MATCH' || quality === 'VETO') {
          next.matchResults = [];
          next.evidenceLedger = [];
        }
      }
      if ((ev.event_type === 'REVIEW_PASSED' || ev.event_type === 'REVIEW_FAILED') && ev.payload) {
        const status = ev.payload.status as string | undefined;
        next.reviewDecision = {
          status,
          failed_checks: ev.payload.failed_checks as string[] | undefined,
          revision_target: (ev.payload.revision_target as string | null | undefined) ?? null,
          revision_reason: (ev.payload.revision_reason as string | undefined) ?? undefined,
          reviewer_summary: ev.payload.reviewer_summary as string | undefined,
          review_id: ev.payload.review_id as string | undefined,
        };
        if (status === 'NO_MATCH' || status === 'VETO' || ev.payload.no_match) {
          next.qualityStatus = status || 'NO_MATCH';
          next.matchResults = [];
          next.evidenceLedger = [];
        } else if (status) {
          next.qualityStatus = status;
        }
      }
      // TASK_RETRY：累计重试次数
      if (ev.event_type === 'TASK_RETRY' && ev.payload?.retry_count != null) {
        next.retryCount = Math.max(state.retryCount, Number(ev.payload.retry_count));
      }
      return next as MissionState;
    });
  },

  reset: () => set({ ...initial }),
}));

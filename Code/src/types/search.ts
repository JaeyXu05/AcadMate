/** 导师信息（临时定义，后续与爬虫同学对齐） */
export interface Advisor {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  /** H 指数（当前 RAG/A 后端均无真实值，暂留作备用；界面用 papers 论文数展示） */
  hIndex?: number;
  /** 仅在 RAG 有可信论文总数时存在；缺失/零值不在界面展示。 */
  papers?: number;
  /** 论文标题列表（来自 RAG candidate.publications，检索时主动展示论文证据） */
  publications?: string[];
  matchScore: number;
  scoreKind?:
    | 'workflow_match'
    | 'interest_overlap'
    | 'content_overlap'
    | 'research_topic_overlap'
    | 'dense_semantic'
    | 'dense_semantic_llm_rerank'
    | 'calibrated_pdf_relevance'
    | 'calibrated_relevance'
    | 'calibrated_relevance_fallback'
    | 'calibrated_relevance_score'
    | 'personalized_recommendation'
    | 'local_rag';
  /** 猜你喜欢中实际命中的兴趣项，用于解释推荐。 */
  matchedInterests?: string[];
  matchType?: 'DIRECT' | 'ADJACENT' | 'UNRELATED' | 'UNASSESSED';
  scoreBreakdown?: Record<string, number>;
  evidence?: Array<{
    evidence_id?: string;
    candidate_id?: string | null;
    source_type?: string;
    source_uri?: string;
    title?: string;
    extracted_fact?: string;
    query_relevance?: number;
    entity_verified?: boolean;
    support_type?: string;
    source_level?: string;
  }>;
  explanation?: string;
  evidenceRefs?: string[];
}

/** 多智能体阶段（审核 / 返工等） */
export interface AgentStage {
  event_type: string;
  summary: string;
  sender?: string;
  receiver?: string;
  timestamp?: string;
  payload?: Record<string, unknown>;
  evidence_refs?: string[];
}

/** 聊天消息 */
export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  advisors?: Advisor[];
  stages?: AgentStage[];
  thinking?: Array<{ agent?: string; text: string }>;
  events?: RuntimeEvent[];
  responseKind?: 'mentor' | 'chat';
}

export type WorkflowEventType =
  | 'WORKFLOW_CREATED' | 'WORKFLOW_RESUMED' | 'INPUT_RECEIVED' | 'INTENT_READY' | 'CLARIFICATION_REQUIRED'
  | 'PLAN_READY' | 'DOMAIN_ANALYSIS_STARTED' | 'DOMAIN_ANALYSIS_READY'
  | 'RESEARCH_STARTED' | 'RESEARCH_DONE' | 'MATCHING_STARTED' | 'MATCHING_DONE'
  | 'REVIEW_STARTED' | 'REVIEW_PASSED' | 'REVIEW_FAILED' | 'TASK_RETRY'
  | 'COMPOSING_RESULT' | 'RESULT_READY' | 'WORKFLOW_COMPLETED' | 'WORKFLOW_FAILED'
  | 'QUERY_CONTRACT_READY' | 'RETRIEVAL_PLAN_READY' | 'RETRIEVER_STARTED'
  | 'RETRIEVER_COMPLETED' | 'CANDIDATES_FUSED' | 'RELATION_JUDGED'
  | 'COVERAGE_INSUFFICIENT' | 'RETRIEVAL_RETRY' | 'ENTITY_VERIFIED'
  | 'EVIDENCE_VERIFIED' | 'QUALITY_GATE_PASSED' | 'NO_QUALIFIED_MATCH'
  | 'EVIDENCE_READY' | 'EVIDENCE_REFS_ONLY' | 'GROWTH_STATE_UPDATED';

export type WorkflowStage =
  | 'input_understanding' | 'planning' | 'domain_expert' | 'mentor_research'
  | 'matching' | 'evidence_review' | 'result_composer' | 'completed' | 'failed';

export interface RuntimeEvent {
  event_type: WorkflowEventType | string;
  stage?: WorkflowStage;
  payload?: Record<string, unknown>;
  evidence_refs?: string[];
  state_version?: number;
  timestamp?: string;
  sender?: string;
  receiver?: string;
  message?: string;
  seq?: number;
}

/** SSE 事件类型 */
export type SseEventType = 'thinking' | 'result' | 'summary' | 'done' | 'error' | 'stage' | 'event';

/** SSE 事件载荷 */
export interface SseEvent {
  type: SseEventType;
  content?: string;
  advisors?: Advisor[];
  message?: string;
  event_type?: string;
  summary?: string;
  sender?: string;
  receiver?: string;
  timestamp?: string;
  payload?: Record<string, unknown>;
  evidence_refs?: string[];
  run_id?: string;
  trace_id?: string;
  review_status?: string;
  suggested_next_skill?: string | null;
  clarification_pending?: boolean;
  threshold?: number;
  response_kind?: 'mentor' | 'chat';
  agent?: string;
  event?: RuntimeEvent;
}

/** 排序方式 */
export type SortBy = 'match' | 'staffId' | 'papers' | 'department';

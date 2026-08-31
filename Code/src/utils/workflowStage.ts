import type { RuntimeEvent, WorkflowStage } from '../types/search';

/** 横条从左到右的阶段（不含 completed/failed） */
export const RUN_STRIP_STAGES: WorkflowStage[] = [
  'input_understanding',
  'planning',
  'domain_expert',
  'mentor_research',
  'matching',
  'evidence_review',
  'result_composer',
];

const SENDER_STAGE: Array<{ key: string; stage: WorkflowStage }> = [
  { key: 'input_understanding', stage: 'input_understanding' },
  { key: 'intake', stage: 'input_understanding' },
  { key: 'planning', stage: 'planning' },
  { key: 'domain_expert', stage: 'domain_expert' },
  { key: 'domain', stage: 'domain_expert' },
  { key: 'retrieval_manager', stage: 'mentor_research' },
  { key: 'mentor_research', stage: 'mentor_research' },
  { key: 'matching', stage: 'matching' },
  { key: 'evidence_review', stage: 'evidence_review' },
  { key: 'result_composer', stage: 'result_composer' },
  { key: 'composer', stage: 'result_composer' },
];

/** 事件发生时「正在跑」的阶段（STARTED / CREATED） */
const START_EVENT_STAGE: Record<string, WorkflowStage> = {
  WORKFLOW_CREATED: 'input_understanding',
  WORKFLOW_RESUMED: 'input_understanding',
  INPUT_RECEIVED: 'input_understanding',
  CLARIFICATION_REQUIRED: 'input_understanding',
  DOMAIN_ANALYSIS_STARTED: 'domain_expert',
  RESEARCH_STARTED: 'mentor_research',
  RETRIEVAL_PLAN_READY: 'mentor_research',
  RETRIEVER_STARTED: 'mentor_research',
  RETRIEVAL_RETRY: 'mentor_research',
  COVERAGE_INSUFFICIENT: 'mentor_research',
  MATCHING_STARTED: 'matching',
  REVIEW_STARTED: 'evidence_review',
  COMPOSING_RESULT: 'result_composer',
};

/** 事件表示该阶段刚完成，应点亮下一格 */
const COMPLETE_EVENT_STAGE: Record<string, WorkflowStage> = {
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
  EVIDENCE_VERIFIED: 'evidence_review',
  ENTITY_VERIFIED: 'evidence_review',
  EVIDENCE_READY: 'evidence_review',
  EVIDENCE_REFS_ONLY: 'evidence_review',
  RESULT_READY: 'result_composer',
};

function stageFromSender(sender?: string): WorkflowStage | null {
  if (!sender) return null;
  const s = sender.toLowerCase();
  for (const row of SENDER_STAGE) {
    if (s.includes(row.key)) return row.stage;
  }
  return null;
}

function asStripStage(stage?: string): WorkflowStage | null {
  if (!stage) return null;
  return RUN_STRIP_STAGES.includes(stage as WorkflowStage) ? (stage as WorkflowStage) : null;
}

/** 从单条 RuntimeEvent 推断当前阶段（缺 stage 字段时也能走） */
export function inferEventStage(ev: {
  event_type?: string;
  stage?: string;
  sender?: string;
}): WorkflowStage | null {
  const explicit = asStripStage(ev.stage);
  if (explicit) return explicit;
  if (ev.stage === 'completed' || ev.stage === 'failed') return ev.stage;
  const type = String(ev.event_type || '');
  if (START_EVENT_STAGE[type]) return START_EVENT_STAGE[type];
  if (COMPLETE_EVENT_STAGE[type]) return COMPLETE_EVENT_STAGE[type];
  if (type === 'TASK_RETRY') return 'mentor_research';
  if (type === 'WORKFLOW_COMPLETED') return 'completed';
  if (type === 'WORKFLOW_FAILED') return 'failed';
  return stageFromSender(ev.sender);
}

export function isStageCompleteEvent(eventType: string): boolean {
  return Boolean(COMPLETE_EVENT_STAGE[eventType]);
}

export interface RunStripProgress {
  activeIdx: number;
  allDone: boolean;
  failed: boolean;
}

/**
 * 按事件顺序推进横条。只把「已经发生过的阶段」标完成，
 * 不会因为第一条事件或最终 completed 把后面的格子提前打勾。
 */
export function progressFromEvents(
  events: Array<{
    event_type?: string;
    stage?: string;
    sender?: string;
    payload?: Record<string, unknown>;
  }>,
  live: boolean,
): RunStripProgress {
  let cursor = -1;
  let completing = false;
  let failed = false;
  let allDone = false;

  for (const ev of events) {
    const type = String(ev.event_type || '');
    if (type === 'TASK_RETRY') {
      const target = String(ev.payload?.revision_target || ev.sender || 'mentor_research');
      const retryStage = inferEventStage({ event_type: type, sender: target }) || 'mentor_research';
      const idx = RUN_STRIP_STAGES.indexOf(retryStage as WorkflowStage);
      if (idx >= 0) {
        cursor = idx - 1;
        completing = true;
        allDone = false;
        failed = false;
      }
      continue;
    }
    if (type === 'WORKFLOW_FAILED' || ev.stage === 'failed') {
      failed = true;
      allDone = true;
      cursor = RUN_STRIP_STAGES.length - 1;
      completing = false;
      continue;
    }
    if (type === 'WORKFLOW_COMPLETED' || ev.stage === 'completed') {
      allDone = true;
      cursor = RUN_STRIP_STAGES.length - 1;
      completing = false;
      continue;
    }

    const stage = inferEventStage(ev);
    if (!stage) continue;
    const idx = RUN_STRIP_STAGES.indexOf(stage as WorkflowStage);
    if (idx < 0) continue;

    const doneHere = isStageCompleteEvent(type);
    if (doneHere) {
      cursor = Math.max(cursor, idx);
      completing = false;
    } else {
      cursor = Math.max(cursor, idx - 1);
      completing = true;
    }
  }

  if (allDone) {
    return { activeIdx: RUN_STRIP_STAGES.length, allDone: true, failed };
  }

  const activeIdx = completing
    ? Math.min(cursor + 1, RUN_STRIP_STAGES.length - 1)
    : cursor < 0
      ? live
        ? 0
        : -1
      : cursor < RUN_STRIP_STAGES.length - 1
        ? cursor + 1
        : cursor;

  return { activeIdx, allDone: false, failed };
}

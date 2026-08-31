import { useState } from 'react';
import type { RuntimeEvent, WorkflowStage } from '../types/search';
import { agentLabel } from '../utils/agentLabel';
import AgentMark from './AgentMark';
import styles from './RuntimeTimeline.module.css';

interface RuntimeTimelineProps {
  events: RuntimeEvent[];
  /** 是否流式中（决定节点是否显示"进行中"脉冲） */
  streaming?: boolean;
  /** 紧凑模式（嵌入气泡内时更小） */
  compact?: boolean;
}

// 阶段展示顺序与中文名（A 的 WorkflowStage，D_PLAN §2.4）
const STAGE_ORDER: WorkflowStage[] = [
  'input_understanding', 'planning', 'domain_expert', 'mentor_research',
  'matching', 'evidence_review', 'result_composer', 'completed',
];
const STAGE_LABEL: Record<string, string> = {
  input_understanding: '意图理解',
  planning: '方案规划',
  domain_expert: '领域分析',
  mentor_research: '导师检索',
  matching: '匹配计算',
  evidence_review: '证据复核',
  result_composer: '结果编排',
  completed: '已完成',
  failed: '失败',
};

// 事件 → 简短展示文案（优先用 payload 里的语义字段，比 hint 文案信息量大）
function eventTitle(ev: RuntimeEvent): string {
  switch (ev.event_type) {
    case 'WORKFLOW_CREATED': return '工作流已创建';
    case 'INPUT_RECEIVED': return '已接收输入需求';
    case 'INTENT_READY': {
      const kc = ev.payload?.topic_count;
      return kc != null ? `意图已确认（${kc} 个方向）` : '意图已确认';
    }
    case 'QUERY_CONTRACT_READY': return '查询语义已锁定（保留限定词）';
    case 'RETRIEVAL_PLAN_READY': return '检索管理器已生成计划';
    case 'RETRIEVER_STARTED': return '开始执行检索器';
    case 'RETRIEVER_COMPLETED': {
      const retriever = ev.payload?.retriever;
      const cc = ev.payload?.candidate_count;
      return retriever != null
        ? `${String(retriever)} 检索完成${cc != null ? `（${cc} 位候选）` : ''}`
        : '检索器执行完成';
    }
    case 'CANDIDATES_FUSED': return '候选结果已融合';
    case 'RELATION_JUDGED': return '查询与候选关系已判定';
    case 'COVERAGE_INSUFFICIENT': return '查询覆盖不足，准备重查';
    case 'RETRIEVAL_RETRY': return '触发检索质量重试';
    case 'ENTITY_VERIFIED': return '导师实体已核验';
    case 'EVIDENCE_VERIFIED': return '候选级证据已核验';
    case 'QUALITY_GATE_PASSED': return '检索质量门通过';
    case 'NO_QUALIFIED_MATCH': return '没有达到相关阈值的导师';
    case 'CLARIFICATION_REQUIRED': return '需要补充信息';
    case 'PLAN_READY': {
      const steps = ev.payload?.steps;
      return Array.isArray(steps) ? `方案已规划（${steps.length} 步）` : '方案已规划';
    }
    case 'DOMAIN_ANALYSIS_STARTED': return '开始领域分析';
    case 'DOMAIN_ANALYSIS_READY': return '领域分析完成';
    case 'RESEARCH_STARTED': return '开始检索导师';
    case 'RESEARCH_DONE': {
      const n = ev.payload?.new_evidence_count;
      const cc = ev.payload?.candidate_count;
      const parts: string[] = [];
      if (cc != null) parts.push(`${cc} 位候选`);
      if (n != null) parts.push(`${n} 条新证据`);
      return parts.length ? `导师检索完成（${parts.join(' · ')}）` : '导师检索完成';
    }
    case 'MATCHING_STARTED': return '开始匹配计算';
    case 'MATCHING_DONE': {
      const mc = ev.payload?.match_count;
      return mc != null ? `匹配完成（${mc} 位）` : '匹配完成';
    }
    case 'REVIEW_STARTED': return '开始证据复核';
    case 'REVIEW_PASSED': return '复核通过';
    case 'REVIEW_FAILED': return '复核未通过';
    case 'TASK_RETRY': {
      const rc = ev.payload?.retry_count;
      const rt = ev.payload?.retry_target;
      return `触发重试${rc ? `（第 ${rc} 次）` : ''}${rt ? ` → ${STAGE_LABEL[rt as string] ?? rt}` : ''}`;
    }
    case 'COMPOSING_RESULT': return '汇总结果中';
    case 'RESULT_READY': {
      const mc = ev.payload?.mentor_count;
      return mc != null ? `结果就绪（${mc} 位导师）` : '结果就绪';
    }
    case 'WORKFLOW_COMPLETED': return '工作流完成';
    case 'WORKFLOW_FAILED': return '工作流失败';
    default: return ev.event_type;
  }
}

// 事件 → 节点视觉类别（绿色通过 / 红色转折 / 蓝色普通 / 灰色起止）
type NodeKind = 'pass' | 'turn' | 'normal' | 'terminal';
function nodeKind(ev: RuntimeEvent): NodeKind {
  switch (ev.event_type) {
    case 'REVIEW_PASSED': return 'pass';
    case 'REVIEW_FAILED':
    case 'TASK_RETRY':
    case 'COVERAGE_INSUFFICIENT':
    case 'RETRIEVAL_RETRY':
    case 'NO_QUALIFIED_MATCH':
      return 'turn';
    case 'WORKFLOW_CREATED':
    case 'WORKFLOW_COMPLETED':
    case 'WORKFLOW_FAILED':
      return 'terminal';
    default: return 'normal';
  }
}

/** 复核未过原因（failed_checks 是当前唯一能"真实解释转折"的字段，D_PLAN §6） */
function failedChecks(ev: RuntimeEvent): string[] {
  const fc = ev.payload?.failed_checks;
  return Array.isArray(fc) ? fc.map((x) => String(x)).filter(Boolean) : [];
}

const CHECK_LABEL: Record<string, string> = {
  evidence_freshness: '证据新鲜度不足（存在 stale 证据）',
  candidate_research_direction_presence: '候选缺少研究方向',
  evidence_fact_support: '证据未能支撑候选字段',
  evidence_reference_integrity: '证据引用完整性问题',
  candidate_presence: '候选为空',
};

function RuntimeTimeline({ events, streaming = false, compact = false }: RuntimeTimelineProps) {
  // 默认展开（右栏 Timeline 需要一眼看到过程；气泡内 compact 仍默认展开，用户可收）
  const [expanded, setExpanded] = useState(true);

  if (!events || events.length === 0) return null;

  // 按事件携带的 stage 分组（无 stage 的归入前一组），保持阶段顺序
  const groups: { stage: WorkflowStage; events: RuntimeEvent[] }[] = [];
  let lastStage: WorkflowStage | undefined;
  for (const ev of events) {
    const st = ev.stage ?? lastStage ?? 'input_understanding';
    if (!lastStage || st !== lastStage) {
      groups.push({ stage: st, events: [ev] });
      lastStage = st;
    } else {
      groups[groups.length - 1].events.push(ev);
    }
  }

  // 按 STAGE_ORDER 排序阶段（未知的排末尾）
  groups.sort((a, b) => {
    const ia = STAGE_ORDER.indexOf(a.stage);
    const ib = STAGE_ORDER.indexOf(b.stage);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
  });

  const hasTurn = events.some((e) => e.event_type === 'REVIEW_FAILED' || e.event_type === 'TASK_RETRY');
  const lastEv = events[events.length - 1];

  return (
    <div className={`${styles.timeline} ${compact ? styles.compact : ''}`}>
      <button
        type="button"
        className={styles.toggle}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className={styles.arrow}>{expanded ? '▾' : '▸'}</span>
        <span className={styles.label}>
          运行时间线（{events.length} 事件）
          {hasTurn && <span className={styles.turnBadge}>含复核转折</span>}
          {streaming && <span className={styles.liveDot} />}
        </span>
      </button>

      {expanded && (
        <div className={styles.groups}>
          {groups.map((g, gi) => (
            <div key={`${g.stage}-${gi}`} className={styles.group}>
              <div className={styles.stageHeader}>
                <span className={styles.stageDot} />
                <span className={styles.stageName}>{STAGE_LABEL[g.stage] ?? g.stage}</span>
                <span className={styles.stageCount}>{g.events.length}</span>
              </div>
              <ul className={styles.eventList}>
                {g.events.map((ev, ei) => {
                  const kind = nodeKind(ev);
                  const checks = ev.event_type === 'REVIEW_FAILED' ? failedChecks(ev) : [];
                  const newEv = ev.payload?.new_evidence_count as number | undefined;
                  return (
                    <li key={ei} className={`${styles.eventItem} ${styles[kind]}`}>
                      <span className={styles.eventDot} />
                      <div className={styles.eventBody}>
                        <div className={styles.eventTitle}>{eventTitle(ev)}</div>
                        <div className={styles.eventMeta}>
                          <span className={styles.eventAgent}>
                            <AgentMark Icon={agentLabel(ev.sender).Icon} />
                            {agentLabel(ev.sender).name}
                          </span>
                          {ev.state_version != null && (
                            <span className={styles.eventVer}>v{ev.state_version}</span>
                          )}
                          {ev.event_type === 'RESEARCH_DONE' && newEv != null && (
                            <span className={styles.eventTag}>+{newEv} 证据</span>
                          )}
                          {ev.event_type === 'REVIEW_PASSED' && (
                            <span className={styles.eventPass}>复核通过</span>
                          )}
                        </div>
                        {/* 转折原因：透传 failed_checks 让 Timeline 解释"为什么转折" */}
                        {checks.length > 0 && (
                          <ul className={styles.checkList}>
                            {checks.map((c, ci) => (
                              <li key={ci} className={styles.checkItem}>
                                <span className={styles.checkDot}>!</span>
                                {CHECK_LABEL[c] ?? c}
                              </li>
                            ))}
                          </ul>
                        )}
                        {ev.event_type === 'TASK_RETRY' && ev.payload?.revision_reason != null && (
                          <div className={styles.reason}>{String(ev.payload.revision_reason)}</div>
                        )}
                        {ev.evidence_refs && ev.evidence_refs.length > 0 && (
                          <div className={styles.evidenceRefs}>
                            证据：{ev.evidence_refs.slice(0, 3).join(', ')}
                            {ev.evidence_refs.length > 3 ? ` …+${ev.evidence_refs.length - 3}` : ''}
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {/* 进行中提示：流式且最后一个事件不是终态 */}
          {streaming && lastEv && !['WORKFLOW_COMPLETED', 'WORKFLOW_FAILED', 'RESULT_READY'].includes(lastEv.event_type) && (
            <div className={styles.running}>运行中…</div>
          )}
        </div>
      )}
    </div>
  );
}

export default RuntimeTimeline;

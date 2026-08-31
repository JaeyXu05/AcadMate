import { useMissionStore } from '../stores/missionStore';
import RuntimeTimeline from './RuntimeTimeline';
import styles from './EvidenceReviewPanel.module.css';

const CHECK_LABEL: Record<string, string> = {
  evidence_freshness: '证据新鲜度不足',
  candidate_research_direction_presence: '候选缺少研究方向',
  evidence_fact_support: '证据未支撑字段',
  evidence_reference_integrity: '证据引用问题',
  candidate_presence: '候选为空',
  no_qualified_match: '没有达到相关阈值的导师',
  publication_count_contradiction: '论文计数与论文证据矛盾',
};

const FRESHNESS_COLOR: Record<string, string> = {
  current: '#64748b',
  recent: '#94a3b8',
  stale: '#cbd5e1',
  unknown: '#e2e8f0',
};
const FRESHNESS_LABEL: Record<string, string> = {
  current: '现期',
  recent: '较新',
  stale: '过期',
  unknown: '未知',
};

// 复核状态 → 大白话 + 颜色语义（普通用户不用理解 REVIEW_AGAIN 这类英文）
const STATUS_PLAIN: Record<string, { label: string; ok: boolean; turn: boolean }> = {
  PASS: { label: '通过 ✓', ok: true, turn: false },
  REVIEW_PASSED: { label: '通过 ✓', ok: true, turn: false },
  NO_MATCH: { label: '无匹配', ok: false, turn: false },
  RESEARCH_AGAIN: { label: '重查', ok: false, turn: true },
  REVISE: { label: '需修正', ok: false, turn: true },
  NEED_MORE_INPUT: { label: '缺信息', ok: false, turn: true },
  FAILED: { label: '未通过', ok: false, turn: true },
  VETO: { label: '已否决', ok: false, turn: true },
};

// 证据来源 type → 中文（原始值如 ustc_official_faculty_profile 对用户是噪音）
const SOURCE_PLAIN: Record<string, string> = {
  ustc_official_faculty_profile: '科大师资主页',
  openalex: 'OpenAlex 论文库',
  s2: 'Semantic Scholar',
  semantic_scholar: 'Semantic Scholar',
};
function sourceLabel(sourceType?: string): string {
  if (!sourceType) return '';
  if (SOURCE_PLAIN[sourceType]) return SOURCE_PLAIN[sourceType];
  // 兜底：把下划线换成空格，去掉 ustc_official_ 前缀，可读一点
  return sourceType.replace(/_/g, ' ').replace(/^ustc /, '');
}

/**
 * Mission 右区：Timeline + Evidence + Review（D_PLAN §5.3）。
 * - Timeline：§5.2 的 RuntimeTimeline（事件分阶段，复核转折醒目）
 * - Review：missionStore.reviewDecision（status / failed_checks / revision_target）
 * - Evidence：missionStore.evidenceLedger（含 freshness，§7.2 也用）
 * 真实 A 路径常态显示 PASS（D_PLAN §6/§2.9），别把"必有转折"当默认。
 */
function EvidenceReviewPanel() {
  const events = useMissionStore((s) => s.events);
  const running = useMissionStore((s) => s.running);
  const reviewDecision = useMissionStore((s) => s.reviewDecision);
  const evidenceLedger = useMissionStore((s) => s.evidenceLedger);
  const matchResults = useMissionStore((s) => s.matchResults);
  const qualityStatus = useMissionStore((s) => s.qualityStatus);

  const noMatch = Boolean(
    qualityStatus === 'NO_MATCH'
    || qualityStatus === 'VETO'
    || reviewDecision?.failed_checks?.includes('no_qualified_match')
    || reviewDecision?.status === 'NO_MATCH'
    || reviewDecision?.status === 'VETO',
  );
  const visibleMatches = noMatch
    ? []
    : matchResults.filter((item) =>
      Number(item.total_score) >= 60
      && item.match_type !== 'UNASSESSED'
      && item.match_type !== 'UNRELATED',
    );
  const allowedIds = new Set(visibleMatches.map((item) => item.candidate_id).filter(Boolean) as string[]);
  const visibleEvidence = noMatch
    ? []
    : evidenceLedger.filter((item) =>
      Boolean(item.candidate_id)
      && allowedIds.has(String(item.candidate_id))
      && (item.support_type === 'DIRECT' || item.support_type === 'ADJACENT')
      && item.source_level !== 'L5'
      && Number(item.query_relevance ?? 1) > 0,
    );
  const evidenceGroups = [...visibleEvidence.reduce((groups, item) => {
    const key = item.candidate_id || 'unbound';
    if (key === 'unbound') return groups;
    const values = groups.get(key) || [];
    values.push(item);
    groups.set(key, values);
    return groups;
  }, new Map<string, typeof visibleEvidence>()).entries()];

  const isPass = reviewDecision?.status === 'PASS' && !noMatch;
  const statusPlain = reviewDecision?.status ? STATUS_PLAIN[reviewDecision.status] : undefined;
  const showStatusPlain = Boolean(reviewDecision?.status) && Boolean(statusPlain);

  return (
    <div className={styles.panel}>
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTitle}>运行时间线</span>
        </div>
        {events.length > 0 ? (
          <RuntimeTimeline events={events} streaming={running} />
        ) : (
          <div className={styles.hint}>开始检索后，这里会按时间顺序记录 AI 的每一步动作，让你看清它是怎么找到结果的。</div>
        )}
      </div>

      {/* 复核决定 */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTitle}>依据核查</span>
            {showStatusPlain && (
            <span
              className={`${styles.reviewPill} ${statusPlain!.ok && !noMatch ? styles.reviewPass : ''} ${statusPlain!.turn || noMatch ? styles.reviewTurn : ''}`}
            >
              {noMatch ? '无匹配' : statusPlain!.label}
            </span>
          )}
        </div>
        {reviewDecision ? (
          <div className={styles.reviewBody}>
            {reviewDecision.reviewer_summary && (
              <div className={styles.reviewSummary}>{reviewDecision.reviewer_summary}</div>
            )}
            {reviewDecision.failed_checks && reviewDecision.failed_checks.length > 0 && (
              <ul className={styles.checkList}>
                {reviewDecision.failed_checks.map((c, i) => (
                  <li key={i} className={styles.checkItem}>
                    <span className={styles.checkDot}>!</span>
                    {CHECK_LABEL[c] ?? CHECK_LABEL[c.split(':')[0]] ?? c}
                  </li>
                ))}
              </ul>
            )}
            {reviewDecision.revision_target && (
              <div className={styles.revision}>
                需要重查：{reviewDecision.revision_target}
              </div>
            )}
            {isPass && !reviewDecision.failed_checks?.length && visibleMatches.length > 0 && (
              <div className={styles.passNote}>✓ 推荐依据够新、查证一致，结果可信。</div>
            )}
            {noMatch && (
              <div className={styles.passNote}>没有合格候选。系统不会用全库凑满名单。</div>
            )}
          </div>
        ) : (
          <div className={styles.hint}>
            {events.length === 0
              ? 'AI 会检查推荐这些老师所依据的信息是否够新、够可靠，结果会显示在这里。'
              : '正在核查推荐依据，请稍候。'}
          </div>
        )}
      </div>

      {/* 每位导师的推荐依据链（来自 match_results.rationale，比一个"通过"更详细） */}
      {visibleMatches.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHeader}>
            <span className={styles.sectionTitle}>推荐依据链</span>
            {visibleMatches.length > 0 && (
              <span className={styles.count}>{visibleMatches.length} 位</span>
            )}
          </div>
          <ul className={styles.rationaleList}>
            {visibleMatches.map((m, mi) => {
              const rationale = Array.isArray(m.rationale) ? m.rationale : [];
              return (
                <li key={m.candidate_id ?? mi} className={styles.rationaleItem}>
                  <div className={styles.rationaleHead}>
                    <span className={styles.rationaleRank}>#{m.ranking_position ?? mi + 1}</span>
                    <span className={styles.rationaleScore}>匹配 {m.total_score} 分</span>
                  </div>
                  {rationale.length > 0 ? (
                    <ul className={styles.rationaleLines}>
                      {rationale.map((r, ri) => (
                        <li key={ri} className={styles.rationaleLine}>{r}</li>
                      ))}
                    </ul>
                  ) : (
                    <div className={styles.rationaleEmpty}>暂无详细依据</div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* 证据账本（新鲜度） */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <span className={styles.sectionTitle}>参考依据</span>
          {visibleEvidence.length > 0 && (
            <span className={styles.count}>{visibleEvidence.length} 条</span>
          )}
        </div>
        {visibleEvidence.length > 0 ? (
          <div>
            {evidenceGroups.map(([candidateId, records]) => (
              <div key={candidateId} style={{ marginBottom: 14 }}>
                <div style={{ color: 'rgba(255,255,255,.55)', fontSize: 12, marginBottom: 7 }}>
                  {candidateId === 'unbound' ? '未绑定证据（不参与导师结论）' : `导师实体：${candidateId}`}
                </div>
                <ul className={styles.evidenceList}>
                  {records.slice(0, 10).map((ev, i) => (
                    <li key={ev.evidence_id ?? i} className={styles.evidenceItem}>
                      <span className={styles.freshnessTag} style={{ color: FRESHNESS_COLOR[ev.freshness ?? 'unknown'] || FRESHNESS_COLOR.unknown }}>
                        {(FRESHNESS_LABEL[ev.freshness ?? 'unknown']) || ev.freshness || '—'}
                      </span>
                      <div className={styles.evidenceBody}>
                        <div className={styles.evidenceTitle}>{ev.title || ev.extracted_fact?.slice(0, 40) || '依据'}</div>
                        <div className={styles.evidenceSource}>
                          {sourceLabel(ev.source_type)} · {ev.source_level || 'L5'} · {ev.support_type || 'UNASSESSED'}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.hint}>
            推荐结果出来后，这里会列出每条依据来自哪里、新旧程度，你可以自己判断靠不靠谱。
          </div>
        )}
      </div>
    </div>
  );
}

export default EvidenceReviewPanel;

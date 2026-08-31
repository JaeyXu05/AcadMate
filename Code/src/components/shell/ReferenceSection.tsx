import { useMissionStore } from '../../stores/missionStore';

const CHECK_LABEL: Record<string, string> = {
  evidence_freshness: '证据新鲜度不足',
  candidate_research_direction_presence: '候选缺少研究方向',
  evidence_fact_support: '证据未支撑字段',
  evidence_reference_integrity: '证据引用问题',
  candidate_presence: '候选为空',
  no_qualified_match: '没有达到相关阈值的导师',
  publication_count_contradiction: '论文计数与论文证据矛盾',
};

const FRESHNESS_LABEL: Record<string, string> = {
  current: '现期',
  recent: '较新',
  stale: '过期',
  unknown: '未知',
};

const STATUS_PLAIN: Record<string, { label: string; ok: boolean }> = {
  PASS: { label: '通过', ok: true },
  REVIEW_PASSED: { label: '通过', ok: true },
  NO_MATCH: { label: '无匹配', ok: false },
  RESEARCH_AGAIN: { label: '重查', ok: false },
  REVISE: { label: '需修正', ok: false },
  NEED_MORE_INPUT: { label: '缺信息', ok: false },
  FAILED: { label: '未通过', ok: false },
  VETO: { label: '已否决', ok: false },
};

const SOURCE_PLAIN: Record<string, string> = {
  ustc_official_faculty_profile: '科大师资主页',
  openalex: 'OpenAlex 论文库',
  s2: 'Semantic Scholar',
  semantic_scholar: 'Semantic Scholar',
};

function sourceLabel(sourceType?: string): string {
  if (!sourceType) return '';
  if (SOURCE_PLAIN[sourceType]) return SOURCE_PLAIN[sourceType];
  return sourceType.replace(/_/g, ' ').replace(/^ustc /, '');
}

function ReferenceSection() {
  const reviewDecision = useMissionStore((s) => s.reviewDecision);
  const evidenceLedger = useMissionStore((s) => s.evidenceLedger);
  const matchResults = useMissionStore((s) => s.matchResults);
  const qualityStatus = useMissionStore((s) => s.qualityStatus);
  const events = useMissionStore((s) => s.events);

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

  const statusPlain = reviewDecision?.status ? STATUS_PLAIN[reviewDecision.status] : undefined;
  const isPass = reviewDecision?.status === 'PASS' && !noMatch;

  return (
    <section className="mt-10">
      <div className="mb-4 flex items-baseline gap-3">
        <span className="font-mono text-[11px] tracking-wide text-slate-400">02</span>
        <h2 className="text-sm font-semibold text-slate-800">
          参考依据
        </h2>
        {statusPlain && (
          <span className="text-[11px] text-slate-500">
            {noMatch ? '无匹配' : statusPlain.label}
          </span>
        )}
      </div>

      {reviewDecision ? (
        <div className="mb-6 space-y-2 text-[13px] leading-relaxed text-slate-600">
          {reviewDecision.reviewer_summary && <p>{reviewDecision.reviewer_summary}</p>}
          {reviewDecision.failed_checks && reviewDecision.failed_checks.length > 0 && (
            <ol className="space-y-1.5">
              {reviewDecision.failed_checks.map((c, i) => (
                <li key={i} className="flex gap-2">
                  <span className="w-4 shrink-0 font-mono text-[10px] text-slate-500">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span>{CHECK_LABEL[c] ?? CHECK_LABEL[c.split(':')[0]] ?? c}</span>
                </li>
              ))}
            </ol>
          )}
          {reviewDecision.revision_target && (
            <p className="text-slate-500">需要重查：{reviewDecision.revision_target}</p>
          )}
          {isPass && !reviewDecision.failed_checks?.length && visibleMatches.length > 0 && (
            <p>推荐依据够新、查证一致。</p>
          )}
          {noMatch && <p>没有合格候选，不会用全库凑名单。</p>}
        </div>
      ) : (
        <p className="mb-6 text-[13px] leading-relaxed text-slate-500">
          {events.length === 0
            ? '核查结果会显示在这里。'
            : '正在核查推荐依据。'}
        </p>
      )}

      {visibleMatches.length > 0 && (
        <ol className="mb-6 space-y-4">
          {visibleMatches.map((m, mi) => {
            const rationale = Array.isArray(m.rationale) ? m.rationale : [];
            return (
              <li key={m.candidate_id ?? mi}>
                <div className="mb-1 flex items-baseline gap-2 text-[12px] text-slate-600">
                  <span className="font-mono text-[10px] text-slate-500">
                    {String(m.ranking_position ?? mi + 1).padStart(2, '0')}
                  </span>
                  <span>匹配 {m.total_score}</span>
                </div>
                {rationale.length > 0 ? (
                  <ul className="space-y-1 pl-6 text-[12.5px] leading-relaxed text-slate-600">
                    {rationale.map((r, ri) => (
                      <li key={ri}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="pl-6 text-[12px] text-slate-500">暂无详细依据</p>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {visibleEvidence.length > 0 ? (
        <div className="space-y-5">
          {evidenceGroups.map(([candidateId, records]) => (
            <div key={candidateId}>
              <div className="mb-2 font-mono text-[10px] tracking-wide text-slate-500">
                {candidateId}
              </div>
              <ol className="space-y-3">
                {records.slice(0, 10).map((ev, i) => (
                  <li key={ev.evidence_id ?? i} className="flex gap-2">
                    <span className="w-4 shrink-0 font-mono text-[10px] text-slate-500">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <div className="min-w-0">
                      <div className="text-sm font-medium leading-relaxed text-slate-700">
                        {ev.title || ev.extracted_fact?.slice(0, 40) || '依据'}
                      </div>
                      <div className="mt-0.5 text-xs leading-relaxed text-slate-500">
                        {FRESHNESS_LABEL[ev.freshness ?? 'unknown'] || ev.freshness || '—'}
                        {' · '}
                        {sourceLabel(ev.source_type)}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[13px] leading-relaxed text-slate-500">
          结果出来后，会列出每条依据的来源与新旧程度。
        </p>
      )}
    </section>
  );
}

export default ReferenceSection;

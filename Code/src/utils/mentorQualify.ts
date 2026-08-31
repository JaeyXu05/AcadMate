import type { Advisor } from '../types/search';

/** 与后端默认 MENTOR_RELEVANCE_THRESHOLD 对齐；SSE 可下发更严的 threshold。 */
export const DISPLAY_RELEVANCE_THRESHOLD = 60;

export function keepDisplayableAdvisors(
  advisors: Advisor[] | undefined,
  threshold = DISPLAY_RELEVANCE_THRESHOLD,
): Advisor[] {
  const floor = Number.isFinite(threshold) && threshold > 0 ? threshold : DISPLAY_RELEVANCE_THRESHOLD;
  return (advisors ?? []).filter((advisor) => {
    const score = Number(advisor.matchScore);
    if (!Number.isFinite(score) || score < floor) return false;
    if (advisor.matchType !== 'DIRECT' && advisor.matchType !== 'ADJACENT') return false;
    const topic = Number(advisor.scoreBreakdown?.topic_match);
    if (Number.isFinite(topic) && topic <= 0) return false;
    return true;
  });
}

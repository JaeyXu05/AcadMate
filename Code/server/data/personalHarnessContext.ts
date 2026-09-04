import { createHash } from 'node:crypto';
import { loadTrustedAgentContext } from './growthStore';
import { listRunArtifacts } from './runArtifacts';

function compact(value: unknown, limit = 260): unknown {
  if (typeof value === 'string') return value.trim().replace(/\s+/g, ' ').slice(0, limit);
  if (Array.isArray(value)) return value.slice(0, 6).map((item) => compact(item, 140));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !/token|secret|password|raw|content/i.test(key))
      .slice(0, 10).map(([key, item]) => [key, compact(item, 140)]));
  }
  return value;
}

function refs(value: unknown): string[] {
  if (!value || typeof value !== 'object') return [];
  const own = (value as Record<string, unknown>).evidence_refs;
  return Array.isArray(own) ? own.map(String).filter(Boolean).slice(0, 5) : [];
}

/** Build a bounded, explainable user-history view for planning/report prompts. */
export function buildPersonalHarnessContext(userId: number, plans: unknown[] = []) {
  const trusted = loadTrustedAgentContext(userId);
  const growth = trusted.growth;
  const artifacts = listRunArtifacts(userId)
    .filter((item) => ['mentor_match', 'paper_qa', 'direction_explore', 'research_task', 'pdf_analyze'].includes(String(item.skillId)) && item.reviewStatus === 'PASS')
    .slice(0, 8)
    .map((item) => {
      const payload = item.payload as Record<string, unknown>;
      const artifact = payload.artifact && typeof payload.artifact === 'object' ? payload.artifact as Record<string, unknown> : payload;
      return { evidence_ref: `run:${item.runId}`, skill: item.skillId, summary: compact({ title: artifact.title ?? artifact.mentor_name ?? item.query, result: artifact.summary ?? artifact.recommendation ?? artifact.research_tasks ?? '' }), evidence_refs: refs(artifact) };
    });
  const summary = {
    profile: compact(trusted.profile),
    research_directions: compact(growth.directions),
    verified_experiences: compact(growth.verified_experiences),
    research_tasks: compact(growth.research_tasks),
    mentor_and_paper_history: compact({ mentors: growth.matched_mentors, papers: growth.read_papers }),
    reviewed_artifacts: artifacts,
  };
  const audit = {
    source: 'personal_harness_summary_v1',
    profile_fields: Object.keys(trusted.profile).filter((key) => Boolean(trusted.profile[key])),
    growth_counts: { directions: growth.directions.length, verified_experiences: growth.verified_experiences.length, research_tasks: growth.research_tasks.length, matched_mentors: growth.matched_mentors.length, read_papers: growth.read_papers.length },
    reviewed_artifact_count: artifacts.length,
    plan_count: plans.length,
  };
  const fingerprint = createHash('sha256').update(JSON.stringify({ summary, plans: compact(plans, 420) })).digest('hex');
  return { trusted, summary, audit, fingerprint };
}

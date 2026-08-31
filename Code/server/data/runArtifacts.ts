import { getDb } from '../db';

export interface RunArtifactRecord {
  userId: number;
  runId: string;
  traceId?: string | null;
  skillId: string;
  query?: string | null;
  reviewStatus?: string | null;
  payload: Record<string, unknown>;
}

function parseJsonObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== 'string' || !value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}

export function saveRunArtifact(input: RunArtifactRecord): void {
  getDb()
    .prepare(
      `INSERT INTO run_artifacts (
         user_id, run_id, trace_id, skill_id, query, review_status, payload_json, created_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
       ON CONFLICT(user_id, run_id, skill_id) DO UPDATE SET
         trace_id = excluded.trace_id,
         query = excluded.query,
         review_status = excluded.review_status,
         payload_json = excluded.payload_json`,
    )
    .run(
      input.userId,
      input.runId,
      input.traceId ?? null,
      input.skillId,
      input.query ?? null,
      input.reviewStatus ?? null,
      JSON.stringify(input.payload),
    );
}

export function loadRunArtifactByRunId(userId: number, runId: string): Record<string, unknown> | null {
  const row = getDb()
    .prepare(
      `SELECT user_id, run_id, trace_id, skill_id, query, review_status, payload_json, created_at
       FROM run_artifacts
       WHERE user_id = ? AND run_id = ?
       ORDER BY created_at DESC, id DESC
       LIMIT 1`,
    )
    .get(userId, runId) as Record<string, unknown> | undefined;
  if (!row) return null;
  return {
    userId: Number(row.user_id),
    runId: String(row.run_id),
    traceId: row.trace_id ? String(row.trace_id) : null,
    skillId: String(row.skill_id),
    query: row.query ? String(row.query) : null,
    reviewStatus: row.review_status ? String(row.review_status) : null,
    payload: parseJsonObject(row.payload_json),
    createdAt: row.created_at,
  };
}

export function listRunArtifacts(
  userId: number,
  filter?: { skillId?: string; advisorId?: string },
): Array<Record<string, unknown>> {
  const rows = (
    filter?.skillId
      ? getDb()
        .prepare(
          `SELECT user_id, run_id, trace_id, skill_id, query, review_status, payload_json, created_at
           FROM run_artifacts
           WHERE user_id = ? AND skill_id = ?
           ORDER BY created_at DESC, id DESC`,
        )
        .all(userId, filter.skillId)
      : getDb()
        .prepare(
          `SELECT user_id, run_id, trace_id, skill_id, query, review_status, payload_json, created_at
           FROM run_artifacts
           WHERE user_id = ?
           ORDER BY created_at DESC, id DESC`,
        )
        .all(userId)
  ) as Array<Record<string, unknown>>;
  return rows
    .map((row) => ({
      userId: Number(row.user_id),
      runId: String(row.run_id),
      traceId: row.trace_id ? String(row.trace_id) : null,
      skillId: String(row.skill_id),
      query: row.query ? String(row.query) : null,
      reviewStatus: row.review_status ? String(row.review_status) : null,
      payload: parseJsonObject(row.payload_json),
      createdAt: row.created_at,
    }))
    .filter((row) => {
      if (!filter?.advisorId) return true;
      return JSON.stringify(row.payload).includes(filter.advisorId)
        || String(row.query || '') === filter.advisorId;
    });
}

export function loadLatestMentorMatchArtifact(
  userId: number,
  advisorId?: string,
): Record<string, unknown> | null {
  const rows = listRunArtifacts(userId, { skillId: 'mentor_match', advisorId });
  for (const row of rows) {
    const payload = row.payload as Record<string, unknown>;
    const advisors = Array.isArray(payload.advisors) ? payload.advisors : [];
    const hit = advisorId
      ? advisors.find((item) => item && typeof item === 'object'
        && String((item as Record<string, unknown>).id ?? '') === advisorId)
      : advisors[0];
    if (!hit || typeof hit !== 'object') continue;
    return {
      ...payload,
      advisor: hit,
      query: row.query,
      run_id: row.runId,
      trace_id: row.traceId,
      review_status: row.reviewStatus,
    };
  }
  return null;
}

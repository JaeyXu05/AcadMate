import { getDb } from '../db';
import { longTermInterestTerms } from './mentorRetrieval';

export interface GrowthStateRecord {
  matched_mentors: unknown[];
  directions: string[];
  read_papers: unknown[];
  verified_experiences: unknown[];
  artifacts: unknown[];
  research_tasks: unknown[];
  direction_hypotheses: unknown[];
  state_version?: number;
}

export interface ReviewedGrowthWrite {
  runId: string;
  skillId: string;
  reviewStatus: string;
  patch: Partial<GrowthStateRecord>;
}

export interface GrowthEventInput {
  verb: string;
  objectType: string;
  objectId: string;
  result?: Record<string, unknown>;
  context?: Record<string, unknown>;
  sourceRunId?: string | null;
  sourceSkillId?: string | null;
}

export interface PendingGrowthWrite {
  id: number;
  userId: number;
  skillId: string;
  runId: string | null;
  traceId: string | null;
  query: string | null;
  payload: Record<string, unknown>;
  status: string;
  attemptCount: number;
}

const EMPTY_GROWTH: GrowthStateRecord = {
  matched_mentors: [],
  directions: [],
  read_papers: [],
  verified_experiences: [],
  artifacts: [],
  research_tasks: [],
  direction_hypotheses: [],
  state_version: 0,
};

function parseJsonArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
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

function uniqueStrings(items: unknown[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const value = String(item ?? '').trim();
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

function mergeByKey(
  current: unknown[],
  incoming: unknown[],
  keyOf: (item: Record<string, unknown>) => string,
): unknown[] {
  const merged = new Map<string, Record<string, unknown>>();
  for (const raw of [...current, ...incoming]) {
    if (!raw || typeof raw !== 'object') continue;
    const item = raw as Record<string, unknown>;
    const key = keyOf(item);
    if (!key) continue;
    merged.set(key, { ...(merged.get(key) ?? {}), ...item });
  }
  return [...merged.values()];
}

export function loadUserProfile(userId: number): Record<string, unknown> {
  const row = getDb()
    .prepare('SELECT nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(userId) as Record<string, unknown> | undefined;
  if (!row) return {};
  return {
    nickname: row.nickname ?? '',
    grade: row.grade ?? '',
    major: row.major ?? '',
    interests: parseJsonArray(row.interests),
    skills: parseJsonArray(row.skills),
    bio: row.bio ?? '',
  };
}

export function loadTrustedAgentContext(userId: number): {
  growth: GrowthStateRecord;
  profile: Record<string, unknown>;
} {
  return {
    growth: loadGrowthState(userId),
    profile: loadUserProfile(userId),
  };
}

export function loadGrowthState(userId: number): GrowthStateRecord {
  const row = getDb()
    .prepare(
      `SELECT matched_mentors, directions, read_papers,
              verified_experiences, artifacts, research_tasks, direction_hypotheses,
              state_version
       FROM growth_state WHERE user_id = ?`,
    )
    .get(userId) as Record<string, unknown> | undefined;
  if (!row) return { ...EMPTY_GROWTH };
  return {
    matched_mentors: parseJsonArray(row.matched_mentors),
    directions: longTermInterestTerms(uniqueStrings(parseJsonArray(row.directions))),
    read_papers: parseJsonArray(row.read_papers),
    verified_experiences: parseJsonArray(row.verified_experiences),
    artifacts: parseJsonArray(row.artifacts),
    research_tasks: parseJsonArray(row.research_tasks),
    direction_hypotheses: parseJsonArray(row.direction_hypotheses),
    state_version: Number(row.state_version ?? 0),
  };
}

export function appendGrowthEvent(userId: number, event: GrowthEventInput): number {
  const result = getDb()
    .prepare(
      `INSERT OR IGNORE INTO growth_events (
         user_id, verb, object_type, object_id, result_json, context_json,
         source_run_id, source_skill_id
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .run(
      userId,
      event.verb,
      event.objectType,
      event.objectId,
      JSON.stringify(event.result ?? {}),
      JSON.stringify(event.context ?? {}),
      event.sourceRunId ?? null,
      event.sourceSkillId ?? null,
    );
  return Number(result.lastInsertRowid);
}

function persistSnapshot(
  userId: number,
  next: GrowthStateRecord,
  expectedVersion: number,
): boolean {
  const db = getDb();
  if (expectedVersion <= 0) {
    const inserted = db.prepare(
      `INSERT INTO growth_state (
         user_id, matched_mentors, directions, read_papers,
         verified_experiences, artifacts, research_tasks, direction_hypotheses,
         state_version, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now','localtime'))
       ON CONFLICT(user_id) DO NOTHING`,
    ).run(
      userId,
      JSON.stringify(next.matched_mentors),
      JSON.stringify(next.directions),
      JSON.stringify(next.read_papers),
      JSON.stringify(next.verified_experiences),
      JSON.stringify(next.artifacts),
      JSON.stringify(next.research_tasks),
      JSON.stringify(next.direction_hypotheses),
    );
    if (inserted.changes > 0) return true;
  }
  const updated = db.prepare(
    `UPDATE growth_state SET
       matched_mentors = ?,
       directions = ?,
       read_papers = ?,
       verified_experiences = ?,
       artifacts = ?,
       research_tasks = ?,
       direction_hypotheses = ?,
       state_version = state_version + 1,
       updated_at = datetime('now','localtime')
     WHERE user_id = ? AND state_version = ?`,
  ).run(
    JSON.stringify(next.matched_mentors),
    JSON.stringify(next.directions),
    JSON.stringify(next.read_papers),
    JSON.stringify(next.verified_experiences),
    JSON.stringify(next.artifacts),
    JSON.stringify(next.research_tasks),
    JSON.stringify(next.direction_hypotheses),
    userId,
    expectedVersion,
  );
  return updated.changes > 0;
}

function mergeReviewedPatch(
  current: GrowthStateRecord,
  input: ReviewedGrowthWrite,
): GrowthStateRecord {
  const patch = input.patch;
  const provenance = {
    source_run_id: input.runId,
    source_skill_id: input.skillId,
    review_status: input.reviewStatus,
  };
  const withProvenance = (items: unknown[] | undefined): unknown[] =>
    (items ?? []).map((item) =>
      item && typeof item === 'object'
        ? { ...(item as Record<string, unknown>), ...provenance }
        : item,
    );
  return {
    matched_mentors: mergeByKey(
      current.matched_mentors,
      withProvenance(patch.matched_mentors),
      (item) => String(item.id ?? ''),
    ),
    directions: longTermInterestTerms([...current.directions, ...(patch.directions ?? [])]),
    read_papers: mergeByKey(
      current.read_papers,
      withProvenance(patch.read_papers),
      (item) => String(item.paper_id ?? item.candidate_id ?? ''),
    ),
    verified_experiences: mergeByKey(
      current.verified_experiences,
      withProvenance(patch.verified_experiences),
      (item) => String(item.id ?? ''),
    ),
    artifacts: mergeByKey(
      current.artifacts,
      withProvenance(patch.artifacts),
      (item) => String(item.id ?? ''),
    ),
    research_tasks: mergeByKey(
      current.research_tasks,
      withProvenance(patch.research_tasks),
      (item) => String(item.id ?? ''),
    ),
    direction_hypotheses: mergeByKey(
      current.direction_hypotheses,
      withProvenance(patch.direction_hypotheses),
      (item) => String(item.id ?? ''),
    ),
  };
}

/** Growth is append/merge-only and accepts only reviewed AgentRun outputs. */
export function writeReviewedGrowth(
  userId: number,
  input: ReviewedGrowthWrite,
): GrowthStateRecord {
  if (input.reviewStatus !== 'PASS' || !input.runId || !input.skillId) {
    throw new Error('成长状态只接受 Review PASS 的 AgentRun 结果');
  }
  if (!/^\d+$/.test(String(input.runId))) {
    throw new Error('成长状态只接受数值 AgentRun id，拒绝把 trace_id 当 run_id 写入');
  }
  for (const field of [
    'matched_mentors',
    'read_papers',
    'verified_experiences',
    'artifacts',
    'research_tasks',
    'direction_hypotheses',
  ] as const) {
    for (const raw of input.patch[field] ?? []) {
      const item = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
      if (!Array.isArray(item.evidence_refs) || item.evidence_refs.length === 0) {
        throw new Error(`${field} 缺少 Evidence，拒绝写入成长状态`);
      }
    }
  }

  const existing = getDb()
    .prepare(
      `SELECT id FROM growth_events
       WHERE user_id = ? AND source_skill_id = ? AND source_run_id = ? AND verb = 'completed'`,
    )
    .get(userId, input.skillId, input.runId) as { id?: number } | undefined;

  const persist = getDb().transaction(() => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const current = loadGrowthState(userId);
      const next = mergeReviewedPatch(current, input);
      if (persistSnapshot(userId, next, current.state_version ?? 0)) {
        if (!existing) {
          appendGrowthEvent(userId, {
            verb: 'completed',
            objectType: input.skillId,
            objectId: input.runId,
            result: { review_status: input.reviewStatus },
            context: { skill_id: input.skillId },
            sourceRunId: input.runId,
            sourceSkillId: input.skillId,
          });
        }
        return loadGrowthState(userId);
      }
    }
    throw new Error('成长状态写入冲突，请稍后重试');
  });
  return persist();
}

export function hasVerifiedPaperReading(
  userId: number,
  advisorId: string,
  paperTitle?: string,
): boolean {
  const growth = loadGrowthState(userId);
  return growth.read_papers.some((raw) => {
    if (!raw || typeof raw !== 'object') return false;
    const item = raw as Record<string, unknown>;
    if (String(item.candidate_id ?? '') !== advisorId) return false;
    if (item.review_status && item.review_status !== 'PASS') return false;
    if (!paperTitle) return true;
    const titles = Array.isArray(item.titles) ? item.titles : [];
    const needle = paperTitle.trim();
    return titles.some((title) => {
      const value = String(title ?? '').trim();
      return value === needle || value.includes(needle) || needle.includes(value);
    });
  });
}

export function findPendingGrowthWrite(input: {
  userId: number;
  skillId: string;
  runId?: string | null;
  traceId?: string | null;
}): PendingGrowthWrite | null {
  const row = (
    input.traceId
      ? getDb()
        .prepare(
          `SELECT id, user_id, skill_id, run_id, trace_id, query, payload_json, status, attempt_count
           FROM pending_growth_writes
           WHERE user_id = ? AND skill_id = ? AND trace_id = ?
           ORDER BY id DESC LIMIT 1`,
        )
        .get(input.userId, input.skillId, input.traceId)
      : input.runId
        ? getDb()
          .prepare(
            `SELECT id, user_id, skill_id, run_id, trace_id, query, payload_json, status, attempt_count
             FROM pending_growth_writes
             WHERE user_id = ? AND skill_id = ? AND run_id = ?
             ORDER BY id DESC LIMIT 1`,
          )
          .get(input.userId, input.skillId, input.runId)
        : undefined
  ) as Record<string, unknown> | undefined;
  if (!row) return null;
  return {
    id: Number(row.id),
    userId: Number(row.user_id),
    skillId: String(row.skill_id),
    runId: row.run_id ? String(row.run_id) : null,
    traceId: row.trace_id ? String(row.trace_id) : null,
    query: row.query ? String(row.query) : null,
    payload: parseJsonObject(row.payload_json),
    status: String(row.status),
    attemptCount: Number(row.attempt_count ?? 0),
  };
}

export function enqueuePendingGrowthWrite(input: {
  userId: number;
  skillId: string;
  runId?: string | null;
  traceId?: string | null;
  query?: string | null;
  payload?: Record<string, unknown>;
  status?: string;
}): number {
  const existing = findPendingGrowthWrite({
    userId: input.userId,
    skillId: input.skillId,
    runId: input.runId,
    traceId: input.traceId,
  });
  if (existing) {
    updatePendingGrowthWrite(existing.id, {
      status: input.status ?? 'polling',
      runId: input.runId ?? existing.runId,
      payload: { ...existing.payload, ...(input.payload ?? {}) },
    });
    return existing.id;
  }
  const result = getDb()
    .prepare(
      `INSERT INTO pending_growth_writes (
         user_id, skill_id, run_id, trace_id, query, payload_json, status, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))`,
    )
    .run(
      input.userId,
      input.skillId,
      input.runId ?? null,
      input.traceId ?? null,
      input.query ?? null,
      JSON.stringify(input.payload ?? {}),
      input.status ?? 'polling',
    );
  return Number(result.lastInsertRowid);
}

export function updatePendingGrowthWrite(
  id: number,
  patch: {
    status?: string;
    runId?: string | null;
    payload?: Record<string, unknown>;
    lastError?: string | null;
    bumpAttempt?: boolean;
    lock?: boolean;
  },
): void {
  const current = getDb()
    .prepare('SELECT payload_json, attempt_count FROM pending_growth_writes WHERE id = ?')
    .get(id) as { payload_json?: string; attempt_count?: number } | undefined;
  const payload = patch.payload ?? parseJsonObject(current?.payload_json);
  const attempts = Number(current?.attempt_count ?? 0) + (patch.bumpAttempt ? 1 : 0);
  getDb()
    .prepare(
      `UPDATE pending_growth_writes
       SET status = COALESCE(?, status),
           run_id = COALESCE(?, run_id),
           payload_json = ?,
           last_error = COALESCE(?, last_error),
           attempt_count = ?,
           locked_at = CASE WHEN ? THEN datetime('now','localtime') ELSE locked_at END,
           updated_at = datetime('now','localtime')
       WHERE id = ?`,
    )
    .run(
      patch.status ?? null,
      patch.runId ?? null,
      JSON.stringify(payload),
      patch.lastError ?? null,
      attempts,
      patch.lock ? 1 : 0,
      id,
    );
}

export function listPendingGrowthWrites(statuses: string[]): PendingGrowthWrite[] {
  if (statuses.length === 0) return [];
  const placeholders = statuses.map(() => '?').join(',');
  const rows = getDb()
    .prepare(
      `SELECT id, user_id, skill_id, run_id, trace_id, query, payload_json, status, attempt_count
       FROM pending_growth_writes
       WHERE status IN (${placeholders})
       ORDER BY id ASC`,
    )
    .all(...statuses) as Array<Record<string, unknown>>;
  return rows.map((row) => ({
    id: Number(row.id),
    userId: Number(row.user_id),
    skillId: String(row.skill_id),
    runId: row.run_id ? String(row.run_id) : null,
    traceId: row.trace_id ? String(row.trace_id) : null,
    query: row.query ? String(row.query) : null,
    payload: parseJsonObject(row.payload_json),
    status: String(row.status),
    attemptCount: Number(row.attempt_count ?? 0),
  }));
}

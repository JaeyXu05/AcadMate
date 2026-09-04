import { getDb } from '../db';

function json(value: unknown): Record<string, unknown> {
  try { const parsed = typeof value === 'string' ? JSON.parse(value) : value; return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {}; } catch { return {}; }
}
export interface ProductivityRun { userId: number; skillId: string; fingerprint: string; runId: string | null; status: string; artifact: Record<string, unknown>; audit: Record<string, unknown>; error: string | null; }
function rowToRun(row: any): ProductivityRun | null {
  return row ? { userId: Number(row.user_id), skillId: String(row.skill_id), fingerprint: String(row.input_fingerprint), runId: row.run_id ? String(row.run_id) : null, status: String(row.status), artifact: json(row.artifact_json), audit: json(row.audit_json), error: row.error ? String(row.error) : null } : null;
}
export function findProductivityRun(userId: number, skillId: string, fingerprint: string): ProductivityRun | null {
  return rowToRun(getDb().prepare('SELECT * FROM productivity_run_cache WHERE user_id=? AND skill_id=? AND input_fingerprint=?').get(userId, skillId, fingerprint));
}
export function findProductivityRunById(userId: number, skillId: string, runId: string): ProductivityRun | null {
  return rowToRun(getDb().prepare('SELECT * FROM productivity_run_cache WHERE user_id=? AND skill_id=? AND run_id=?').get(userId, skillId, runId));
}
export function saveProductivityRun(input: ProductivityRun): ProductivityRun {
  getDb().prepare(`INSERT INTO productivity_run_cache (user_id,skill_id,input_fingerprint,run_id,status,artifact_json,audit_json,error)
    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user_id,skill_id,input_fingerprint) DO UPDATE SET run_id=excluded.run_id,status=excluded.status,artifact_json=excluded.artifact_json,audit_json=excluded.audit_json,error=excluded.error,updated_at=datetime('now','localtime')`)
    .run(input.userId, input.skillId, input.fingerprint, input.runId, input.status, JSON.stringify(input.artifact), JSON.stringify(input.audit), input.error);
  return input;
}

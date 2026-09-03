import crypto from 'crypto';
import { getDb } from '../db';

export type PdfAnalysisJobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface PdfAnalysisJob {
  jobId: string;
  userId: number;
  documentId: string;
  filename: string;
  status: PdfAnalysisJobStatus;
  result: Record<string, unknown> | null;
  error: string | null;
  createdAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
  updatedAt: string | null;
}

function parseResult(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== 'string' || !value) return null;
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function mapJob(row: Record<string, unknown> | undefined): PdfAnalysisJob | null {
  if (!row) return null;
  return {
    jobId: String(row.job_id),
    userId: Number(row.user_id),
    documentId: String(row.document_id),
    filename: String(row.filename ?? ''),
    status: String(row.status || 'failed') as PdfAnalysisJobStatus,
    result: parseResult(row.result_json),
    error: row.error ? String(row.error) : null,
    createdAt: row.created_at ? String(row.created_at) : null,
    startedAt: row.started_at ? String(row.started_at) : null,
    completedAt: row.completed_at ? String(row.completed_at) : null,
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}

const SELECT_JOB = `
  SELECT job_id, user_id, document_id, filename, status, result_json, error,
         created_at, started_at, completed_at, updated_at
    FROM pdf_analysis_jobs
`;

export function createPdfAnalysisJob(userId: number, documentId: string, filename: string): PdfAnalysisJob {
  const jobId = `pdfjob_${Date.now()}_${crypto.randomBytes(6).toString('hex')}`;
  getDb().prepare(`
    INSERT INTO pdf_analysis_jobs (job_id, user_id, document_id, filename, status, updated_at)
    VALUES (?, ?, ?, ?, 'queued', datetime('now', 'localtime'))
  `).run(jobId, userId, documentId, filename);
  return getPdfAnalysisJob(userId, jobId)!;
}

export function findActivePdfAnalysisJob(userId: number, documentId: string): PdfAnalysisJob | null {
  const row = getDb().prepare(`${SELECT_JOB}
    WHERE user_id = ? AND document_id = ? AND status IN ('queued', 'running')
    ORDER BY created_at DESC LIMIT 1`).get(userId, documentId) as Record<string, unknown> | undefined;
  return mapJob(row);
}

export function getPdfAnalysisJob(userId: number, jobId: string): PdfAnalysisJob | null {
  const row = getDb().prepare(`${SELECT_JOB}
    WHERE user_id = ? AND job_id = ? LIMIT 1`).get(userId, jobId) as Record<string, unknown> | undefined;
  return mapJob(row);
}

export function listPdfAnalysisJobs(userId: number, limit = 20): PdfAnalysisJob[] {
  const safeLimit = Math.max(1, Math.min(50, Math.floor(limit)));
  const rows = getDb().prepare(`${SELECT_JOB}
    WHERE user_id = ?
    ORDER BY created_at DESC LIMIT ?`).all(userId, safeLimit) as Array<Record<string, unknown>>;
  return rows.map(mapJob).filter((job): job is PdfAnalysisJob => Boolean(job));
}

export function markPdfAnalysisJobRunning(jobId: string): void {
  getDb().prepare(`
    UPDATE pdf_analysis_jobs
       SET status = 'running', started_at = COALESCE(started_at, datetime('now', 'localtime')),
           updated_at = datetime('now', 'localtime')
     WHERE job_id = ? AND status = 'queued'
  `).run(jobId);
}

export function markPdfAnalysisJobsRunning(jobIds: string[]): void {
  for (const jobId of jobIds) markPdfAnalysisJobRunning(jobId);
}

export function completePdfAnalysisJob(jobId: string, result: Record<string, unknown>): void {
  getDb().prepare(`
    UPDATE pdf_analysis_jobs
       SET status = 'succeeded', result_json = ?, error = NULL,
           completed_at = datetime('now', 'localtime'), updated_at = datetime('now', 'localtime')
     WHERE job_id = ?
  `).run(JSON.stringify(result), jobId);
}

export function completePdfAnalysisJobs(jobIds: string[], result: Record<string, unknown>): void {
  for (const jobId of jobIds) completePdfAnalysisJob(jobId, result);
}

export function failPdfAnalysisJob(jobId: string, error: string): void {
  getDb().prepare(`
    UPDATE pdf_analysis_jobs
       SET status = 'failed', error = ?, completed_at = datetime('now', 'localtime'),
           updated_at = datetime('now', 'localtime')
     WHERE job_id = ?
  `).run(error.slice(0, 1000), jobId);
}

export function failPdfAnalysisJobs(jobIds: string[], error: string): void {
  for (const jobId of jobIds) failPdfAnalysisJob(jobId, error);
}

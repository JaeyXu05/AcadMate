import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import { getDb } from '../db';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
export const DOCUMENTS_DIR = path.join(__dirname, '..', '..', 'data', 'documents');

export interface ResearchDocument {
  documentId: string;
  userId: number;
  contentHash: string;
  originalName: string;
  storedPath: string;
  pageCount: number | null;
  extractedText: string;
  parseStatus: string;
  createdAt: string | null;
  updatedAt: string | null;
}

function ensureDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
}

export function persistUploadedPdf(input: {
  userId: number;
  originalName: string;
  sourcePath: string;
}): ResearchDocument {
  const buffer = fs.readFileSync(input.sourcePath);
  const contentHash = crypto.createHash('sha256').update(buffer).digest('hex');
  const documentId = `u${input.userId}:${contentHash}`;
  const userDir = path.join(DOCUMENTS_DIR, String(input.userId));
  ensureDir(userDir);
  const storedPath = path.join(userDir, `${contentHash}.pdf`);
  if (!fs.existsSync(storedPath)) {
    fs.copyFileSync(input.sourcePath, storedPath);
  }
  const existing = loadResearchDocument(input.userId, documentId);
  if (existing) {
    try { fs.unlinkSync(input.sourcePath); } catch { /* tmp already moved */ }
    return existing;
  }
  getDb()
    .prepare(
      `INSERT INTO research_documents (
         document_id, user_id, content_hash, original_name, stored_path, parse_status
       ) VALUES (?, ?, ?, ?, ?, 'uploaded')
       ON CONFLICT(user_id, content_hash) DO UPDATE SET
         original_name = excluded.original_name,
         stored_path = excluded.stored_path,
         updated_at = datetime('now','localtime')`,
    )
    .run(documentId, input.userId, contentHash, input.originalName, storedPath);
  try { fs.unlinkSync(input.sourcePath); } catch { /* ignore tmp cleanup */ }
  return loadResearchDocument(input.userId, documentId)!;
}

export function loadResearchDocument(userId: number, documentId: string): ResearchDocument | null {
  const row = getDb()
    .prepare(
      `SELECT document_id, user_id, content_hash, original_name, stored_path,
              page_count, extracted_text, parse_status, created_at, updated_at
       FROM research_documents
       WHERE user_id = ? AND document_id = ?`,
    )
    .get(userId, documentId) as Record<string, unknown> | undefined;
  if (!row) return null;
  return {
    documentId: String(row.document_id),
    userId: Number(row.user_id),
    contentHash: String(row.content_hash),
    originalName: String(row.original_name ?? ''),
    storedPath: String(row.stored_path),
    pageCount: row.page_count == null ? null : Number(row.page_count),
    extractedText: String(row.extracted_text ?? ''),
    parseStatus: String(row.parse_status ?? 'uploaded'),
    createdAt: row.created_at ? String(row.created_at) : null,
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}

export function listResearchDocuments(userId: number, limit = 50): ResearchDocument[] {
  const safeLimit = Math.max(1, Math.min(100, Math.floor(limit)));
  const rows = getDb()
    .prepare(
      `SELECT document_id, user_id, content_hash, original_name, stored_path,
              page_count, extracted_text, parse_status, created_at, updated_at
       FROM research_documents
       WHERE user_id = ?
       ORDER BY updated_at DESC, created_at DESC
       LIMIT ?`,
    )
    .all(userId, safeLimit) as Array<Record<string, unknown>>;
  return rows.map((row) => ({
    documentId: String(row.document_id),
    userId: Number(row.user_id),
    contentHash: String(row.content_hash),
    originalName: String(row.original_name ?? ''),
    storedPath: String(row.stored_path),
    pageCount: row.page_count == null ? null : Number(row.page_count),
    extractedText: String(row.extracted_text ?? ''),
    parseStatus: String(row.parse_status ?? 'uploaded'),
    createdAt: row.created_at ? String(row.created_at) : null,
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  }));
}

export function updateResearchDocumentText(
  documentId: string,
  extractedText: string,
  pageCount: number | null,
  parseStatus = 'parsed',
): void {
  getDb()
    .prepare(
      `UPDATE research_documents
       SET extracted_text = ?, page_count = ?, parse_status = ?, updated_at = datetime('now','localtime')
       WHERE document_id = ?`,
    )
    .run(extractedText, pageCount, parseStatus, documentId);
}

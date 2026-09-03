import api from './axios';
import type { PdfUploadResponse, PdfAnalysisResult } from '../types/pdf';

export interface PdfAnalysisJob {
  jobId: string;
  userId: number;
  documentId: string;
  filename: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  result: PdfAnalysisResult | null;
  error: string | null;
  createdAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
  updatedAt: string | null;
}

export interface PdfDocument {
  documentId: string;
  userId: number;
  originalName: string;
  pageCount: number | null;
  parseStatus: string;
  createdAt: string | null;
  updatedAt: string | null;
}

/** 上传 PDF 文件，返回 upload_id（用于后续分析） */
export async function uploadPdf(file: File): Promise<PdfUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post<PdfUploadResponse>('/upload/pdf', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

/** 须覆盖 D 端 MENTOR_AGENT_TIMEOUT_MS（默认 420s）+ PDF 抽文本，避免 axios 先 abort 成假超时 */
export const ANALYZE_TIMEOUT_MS = 8 * 60 * 1000;

/** 创建后台 PDF 分析任务；HTTP 请求很快返回，页面离开后任务仍会继续。 */
export async function analyzePdf(upload_id: string): Promise<{ job_id: string; status: PdfAnalysisJob['status']; document_id: string; filename: string }> {
  const { data } = await api.post<{ job_id: string; status: PdfAnalysisJob['status']; document_id: string; filename: string }>(
    '/pdf/analyze',
    { upload_id },
  );
  return data;
}

/** 多选合并分析：返回一份任务列表，成功后每篇历史记录都会显示同一份合并结果 */
export async function analyzePdfBatch(upload_ids: string[]): Promise<{ jobs: PdfAnalysisJob[] }> {
  const { data } = await api.post<{ jobs: PdfAnalysisJob[] }>('/pdf/analyze-batch', { document_ids: upload_ids });
  return data;
}

export async function getPdfAnalysisJob(jobId: string): Promise<PdfAnalysisJob> {
  return (await api.get<PdfAnalysisJob>(`/pdf/jobs/${encodeURIComponent(jobId)}`)).data;
}

export async function listPdfAnalysisJobs(): Promise<PdfAnalysisJob[]> {
  return (await api.get<{ items: PdfAnalysisJob[] }>('/pdf/jobs')).data.items;
}

export async function listPdfDocuments(): Promise<PdfDocument[]> {
  return (await api.get<{ items: PdfDocument[] }>('/pdf/documents')).data.items;
}

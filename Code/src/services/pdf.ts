import api from './axios';
import type { PdfUploadResponse, PdfAnalysisResult } from '../types/pdf';

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

/** 分析已上传的 PDF；语义检索 + 模型重排通常需要数分钟 */
export async function analyzePdf(upload_id: string): Promise<PdfAnalysisResult> {
  const { data } = await api.post<PdfAnalysisResult>(
    '/pdf/analyze',
    { upload_id },
    { timeout: ANALYZE_TIMEOUT_MS },
  );
  return {
    ...data,
    suggestedAdvisors: (data.suggestedAdvisors ?? []).map((item) => ({
      ...item,
      scoreKind: item.scoreKind || data.scoreKind || 'calibrated_pdf_relevance',
    })),
  };
}

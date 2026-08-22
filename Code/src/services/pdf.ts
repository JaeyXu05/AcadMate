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

/** 分析已上传的 PDF */
export async function analyzePdf(upload_id: string): Promise<PdfAnalysisResult> {
  const { data } = await api.post<PdfAnalysisResult>('/pdf/analyze', { upload_id });
  return data;
}

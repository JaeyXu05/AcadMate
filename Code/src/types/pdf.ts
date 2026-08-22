import type { Advisor } from './search';

/**
 * PDF 分析结果契约。
 *
 * 字段对齐说明：当前为 D（网站搭建）侧临时定义。
 * 队友 A（检索智能体）交付真实分析后若结构有差异，在 services/pdf.ts
 * 的 service 层做映射，保持本类型不变，组件零改动。
 */

/** 上传响应 */
export interface PdfUploadResponse {
  upload_id: string;
  filename: string;
}

/** 分析响应 */
export interface PdfAnalysisResult {
  /** 全文总结 */
  summary: string;
  /** 关键要点（列表） */
  keyPoints: string[];
  /** 据论文内容推荐的导师 */
  suggestedAdvisors: Advisor[];
}

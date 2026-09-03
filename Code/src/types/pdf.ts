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
  document_id?: string;
  /** 多选合并分析时参与的文档列表 */
  document_ids?: string[];
  document_names?: string[];
  /** 多选合并分析的展示标题 */
  batchLabel?: string;
  review_status?: string;
  scoreKind?: Advisor['scoreKind'];
  evidence_refs?: string[];
}

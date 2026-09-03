import fs from 'fs';
import { loadResearchDocument, updateResearchDocumentText } from '../data/researchDocuments';
import {
  completePdfAnalysisJob,
  completePdfAnalysisJobs,
  failPdfAnalysisJob,
  failPdfAnalysisJobs,
  markPdfAnalysisJobsRunning,
  markPdfAnalysisJobRunning,
} from '../data/pdfAnalysisJobs';
import { appendGrowthEvent } from '../data/growthStore';
import { extractPdfPages, buildSummary, buildKeyPoints, type StructuredPdfAnalysis } from '../routes/pdfText';
import { pdfGrowthPatch, isNumericRunId, runHarnessSkill, agentBase, probeAgent, explainAgentError } from '../harnessClient';

function analysisBudget(pages: Array<{ page: number; text: string }>): Array<{ page: number; text: string }> {
  const maxPagesRaw = Number(process.env.PDF_MAX_ANALYSIS_PAGES || 64);
  const maxCharsRaw = Number(process.env.PDF_MAX_ANALYSIS_CHARS || 120000);
  const maxPages = Number.isFinite(maxPagesRaw) ? Math.max(8, Math.min(200, Math.floor(maxPagesRaw))) : 64;
  const maxChars = Number.isFinite(maxCharsRaw) ? Math.max(20000, Math.min(500000, Math.floor(maxCharsRaw))) : 120000;
  if (pages.length <= maxPages && pages.reduce((sum, page) => sum + page.text.length, 0) <= maxChars) return pages;

  // 页数超限时按页码均匀抽样，而不是只保留“前 62 页 + 后 2 页”，
  // 避免长文档中间章节的研究内容在到达 A 端前就整体丢失。
  let selected = [...pages];
  if (pages.length > maxPages) {
    const step = (pages.length - 1) / Math.max(1, maxPages - 1);
    const indexes: number[] = [];
    for (let i = 0; i < maxPages; i += 1) {
      const index = Math.round(i * step);
      if (!indexes.includes(index)) indexes.push(index);
    }
    selected = indexes.map((index) => pages[index]);
  }

  // 字符数仍超限时给每页分配等额预算，保证每一页都保留一部分文本，
  // 而不是把预算全部花在前面的页上、后面的页被截成空文本丢掉。
  const totalChars = selected.reduce((sum, page) => sum + page.text.length, 0);
  if (totalChars > maxChars) {
    const quota = Math.max(1, Math.floor(maxChars / selected.length));
    selected = selected.map((page) => ({ page: page.page, text: page.text.slice(0, quota) }));
  }
  return selected.filter((page) => page.text.trim());
}

function pdfAgentTimeoutMs(): number {
  const configured = Number(process.env.PDF_AGENT_TIMEOUT_MS || 480000);
  return Number.isFinite(configured) ? Math.max(30_000, Math.min(configured, 480_000)) : 480000;
}

/**
 * 在后端独立执行 PDF 分析。它不依赖浏览器请求的生命周期，
 * 因此用户离开 PDF 页面后，A 端任务仍会继续并把结果写入任务表。
 */
export async function processPdfAnalysisJob(jobId: string, userId: number, documentId: string): Promise<void> {
  markPdfAnalysisJobRunning(jobId);
  try {
    const record = loadResearchDocument(userId, documentId);
    if (!record) throw new Error('文档不存在，请重新上传');
    if (!fs.existsSync(record.storedPath)) throw new Error(`文档文件缺失，请重新上传：${record.originalName}`);
    if (!agentBase()) {
      throw new Error('PDF 分析需要 A 端 Mentor Agent（MENTOR_AGENT_BASE_URL）。请先启动 A 端。');
    }
    if (!(await probeAgent(2500))) {
      throw new Error(`Mentor Agent 未启动或无法连接（${agentBase()}）。请先启动 A 端。`);
    }

    const pages = await extractPdfPages(record.storedPath);
    const docText = pages.map((page) => page.text).join('\n');
    if (!pages.length || !docText.trim()) {
      updateResearchDocumentText(record.documentId, '', null, 'empty_text');
      throw new Error(`未能从「${record.originalName}」抽取正文。该文件可能是扫描件、图片 PDF 或已加密。`);
    }
    if (docText !== record.extractedText) {
      updateResearchDocumentText(record.documentId, docText, pages.length, 'parsed');
    }

    const pagesForAnalysis = analysisBudget(pages);
    const result = await runHarnessSkill({
      userId,
      skillId: 'pdf_analyze',
      message: `分析文档 ${record.originalName}`,
      query: record.documentId,
      timeoutMs: pdfAgentTimeoutMs(),
      context: {
        document_id: record.documentId,
        pages: pagesForAnalysis,
        source_page_count: pages.length,
      },
      patcher: (runId, payload) => pdfGrowthPatch(runId, record.documentId, payload),
    });
    const advisors = Array.isArray(result?.artifact?.advisors) ? result.artifact.advisors : [];
    const suggestedAdvisors = advisors.map((item: any) => ({
      id: String(item.id || ''),
      name: String(item.name || ''),
      title: String(item.title || ''),
      department: String(item.department || ''),
      tags: Array.isArray(item.tags) ? item.tags : [],
      papers: Number(item.papers || 0),
      matchScore: Number(item.matchScore || 0),
      explanation: item.explanation,
      evidenceRefs: item.evidenceRefs,
      scoreKind: String(item.scoreKind || 'dense_semantic_llm_rerank'),
    }));
    const reviewStatus = String(result?.review_status || 'NEED_MORE_INPUT');
    const analysis = result?.artifact?.analysis && typeof result.artifact.analysis === 'object'
      ? result.artifact.analysis as StructuredPdfAnalysis
      : undefined;
    if (reviewStatus !== 'PASS' || !analysis) {
      const detail = String(result?.artifact?.error || `Review ${reviewStatus}`);
      appendGrowthEvent(userId, {
        verb: 'analyze_blocked',
        objectType: 'document',
        objectId: record.documentId,
        result: { review_status: reviewStatus, run_id: result?.run_id, error: detail },
        context: { evidence_refs: result?.evidence_refs ?? [] },
        sourceRunId: isNumericRunId(String(result?.run_id || '')) ? String(result.run_id) : null,
        sourceSkillId: 'pdf_analyze',
      });
      throw new Error(`「${record.originalName}」未产出通过审核的分析：${detail}`);
    }

    const summary = buildSummary(docText, [], record.originalName, suggestedAdvisors.length, {
      reviewStatus,
      analysis,
    });
    const keyPoints = buildKeyPoints(docText, [], [], [], {
      reviewStatus,
      advisors: suggestedAdvisors,
      error: result?.artifact?.error,
      analysis,
    });
    appendGrowthEvent(userId, {
      verb: 'analyzed',
      objectType: 'document',
      objectId: record.documentId,
      result: { review_status: reviewStatus, run_id: result?.run_id, advisor_ids: suggestedAdvisors.map((item: any) => item.id) },
      context: { evidence_refs: result?.evidence_refs ?? [] },
      sourceRunId: isNumericRunId(String(result?.run_id || '')) ? String(result.run_id) : null,
      sourceSkillId: 'pdf_analyze',
    });
    completePdfAnalysisJob(jobId, {
      summary,
      keyPoints,
      suggestedAdvisors,
      document_id: record.documentId,
      content_hash: record.contentHash,
      run_id: result?.run_id,
      review_status: reviewStatus,
      evidence_refs: result?.evidence_refs ?? [],
      scoreKind: suggestedAdvisors[0]?.scoreKind || 'dense_semantic_llm_rerank',
    });
  } catch (err) {
    const explained = explainAgentError(err, 'PDF 分析需要 A 端 Harness，当前无法完成。');
    failPdfAnalysisJob(jobId, explained.message);
  }
}

function combinedBatchLabel(names: string[]): string {
  if (names.length <= 3) return names.join('、');
  return `${names[0]} 等 ${names.length} 篇`;
}

/**
 * 多选合并分析：把若干篇 PDF 拼进同一次 A 端 pdf_analyze 调用，
 * 由同一个 LLM 综合所有文献得出结论，而不是每篇单独调用。
 * jobIds 与 documentIds 一一对应，成功后每篇对应的历史任务都会显示同一份合并结果。
 */
export async function processPdfBatchAnalysisJob(
  jobIds: string[],
  userId: number,
  documentIds: string[],
): Promise<void> {
  markPdfAnalysisJobsRunning(jobIds);
  try {
    if (!jobIds.length || jobIds.length !== documentIds.length) {
      throw new Error('批量分析任务参数不一致');
    }
    const records = documentIds.map((documentId) => {
      const record = loadResearchDocument(userId, documentId);
      if (!record) throw new Error(`文档不存在或不属于当前用户：${documentId}`);
      if (!fs.existsSync(record.storedPath)) throw new Error(`文件缺失，请重新上传：${record.originalName}`);
      return record;
    });
    if (!agentBase()) {
      throw new Error('PDF 分析需要 A 端 Mentor Agent（MENTOR_AGENT_BASE_URL）。请先启动 A 端。');
    }
    if (!(await probeAgent(2500))) {
      throw new Error(`Mentor Agent 未启动或无法连接（${agentBase()}）。请先启动 A 端。`);
    }

    const names = records.map((record) => record.originalName);
    const batchLabel = `合并分析（${records.length} 篇）：${combinedBatchLabel(names)}`;
    const combinedPages: Array<{ page: number; text: string }> = [];
    const docTexts: string[] = [];
    let pageCursor = 1;

    for (const record of records) {
      const pages = await extractPdfPages(record.storedPath);
      const docText = pages.map((page) => page.text).join('\n');
      if (!pages.length || !docText.trim()) {
        updateResearchDocumentText(record.documentId, '', null, 'empty_text');
        throw new Error(`未能从「${record.originalName}」抽出正文。该文件可能是扫描件、图片 PDF 或已加密，无法参与合并分析。`);
      }
      if (docText !== record.extractedText) {
        updateResearchDocumentText(record.documentId, docText, pages.length, 'parsed');
      }
      docTexts.push(docText);
      for (const page of pages) {
        combinedPages.push({
          page: pageCursor++,
          text: `【${record.originalName}｜第 ${page.page} 页】 ${page.text}`,
        });
      }
    }

    const fullText = docTexts.join('\n\n');
    const pagesForAnalysis = analysisBudget(combinedPages);
    if (!pagesForAnalysis.length) {
      throw new Error('未能从所选 PDF 中提取到可供检索的正文。');
    }

    const result = await runHarnessSkill({
      userId,
      skillId: 'pdf_analyze',
      message: batchLabel,
      query: documentIds.join('|'),
      timeoutMs: pdfAgentTimeoutMs(),
      context: {
        document_id: `combined:${documentIds.join('+')}`,
        document_ids: documentIds,
        document_names: names,
        pages: pagesForAnalysis,
        source_page_count: combinedPages.length,
      },
    });

    const advisors = Array.isArray(result?.artifact?.advisors) ? result.artifact.advisors : [];
    const suggestedAdvisors = advisors.map((item: any) => ({
      id: String(item.id || ''),
      name: String(item.name || ''),
      title: String(item.title || ''),
      department: String(item.department || ''),
      tags: Array.isArray(item.tags) ? item.tags : [],
      papers: Number(item.papers || 0),
      matchScore: Number(item.matchScore || 0),
      explanation: item.explanation,
      evidenceRefs: item.evidenceRefs,
      scoreKind: String(item.scoreKind || 'dense_semantic_llm_rerank'),
    }));
    const reviewStatus = String(result?.review_status || 'NEED_MORE_INPUT');
    const analysis = result?.artifact?.analysis && typeof result.artifact.analysis === 'object'
      ? result.artifact.analysis as StructuredPdfAnalysis
      : undefined;
    if (reviewStatus !== 'PASS' || !analysis) {
      const detail = String(result?.artifact?.error || `Review ${reviewStatus}`);
      throw new Error(`${batchLabel}：智能体未产出通过审核的分析：${detail}`);
    }

    const summary = buildSummary(fullText, [], batchLabel, suggestedAdvisors.length, {
      reviewStatus,
      analysis,
    });
    const keyPoints = buildKeyPoints(fullText, [], [], [], {
      reviewStatus,
      advisors: suggestedAdvisors,
      error: result?.artifact?.error,
      analysis,
    });
    const resultPayload = {
      summary,
      keyPoints,
      suggestedAdvisors,
      document_id: `combined:${documentIds.join('+')}`,
      document_ids: documentIds,
      document_names: names,
      batchLabel,
      run_id: result?.run_id,
      review_status: reviewStatus,
      evidence_refs: result?.evidence_refs ?? [],
      scoreKind: suggestedAdvisors[0]?.scoreKind || 'dense_semantic_llm_rerank',
    };
    completePdfAnalysisJobs(jobIds, resultPayload);
    for (const record of records) {
      appendGrowthEvent(userId, {
        verb: 'analyzed',
        objectType: 'document',
        objectId: record.documentId,
        result: { review_status: reviewStatus, run_id: result?.run_id, advisor_ids: suggestedAdvisors.map((item: any) => item.id), batch: true },
        context: { evidence_refs: result?.evidence_refs ?? [] },
        sourceRunId: isNumericRunId(String(result?.run_id || '')) ? String(result.run_id) : null,
        sourceSkillId: 'pdf_analyze',
      });
    }
  } catch (err) {
    const explained = explainAgentError(err, 'PDF 合并分析需要 A 端 Harness，当前无法完成。');
    failPdfAnalysisJobs(jobIds, explained.message);
  }
}

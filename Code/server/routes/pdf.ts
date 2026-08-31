import { Router, Response, Request, NextFunction } from 'express';
import multer from 'multer';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { promisify } from 'util';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { persistUploadedPdf, loadResearchDocument, updateResearchDocumentText } from '../data/researchDocuments';
import { appendGrowthEvent } from '../data/growthStore';
import { extractPdfPages, buildSummary, buildKeyPoints, type StructuredPdfAnalysis } from './pdfText';
import { pdfGrowthPatch, isNumericRunId, runHarnessSkill, agentBase, probeAgent, explainAgentError } from '../harnessClient';

const unlink = promisify(fs.unlink);

export const pdfRouter = Router();
export const uploadRouter = Router();

pdfRouter.use(authMiddleware);
uploadRouter.use(authMiddleware);

const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, os.tmpdir()),
  filename: (_req, file, cb) => {
    file.originalname = decodeUploadName(file.originalname);
    const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
    cb(null, `pdf-${unique}${path.extname(file.originalname) || '.pdf'}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 20 * 1024 * 1024 },
  defParamCharset: 'utf8',
  fileFilter: (_req, file, cb) => {
    file.originalname = decodeUploadName(file.originalname);
    if (
      file.mimetype === 'application/pdf' ||
      file.originalname.toLowerCase().endsWith('.pdf')
    ) {
      cb(null, true);
    } else {
      cb(new Error('仅支持 PDF 文件'));
    }
  },
});

/** multer 默认按 latin1 解 Content-Disposition；中文文件名会变成 å°ºäºº 这类乱码。 */
function decodeUploadName(name: string): string {
  if (!name) return name;
  try {
    const repaired = Buffer.from(name, 'latin1').toString('utf8');
    const repairedHasCjk = /[\u4e00-\u9fff]/.test(repaired);
    const originalHasCjk = /[\u4e00-\u9fff]/.test(name);
    if (repairedHasCjk && !originalHasCjk) return repaired;
  } catch {
    /* keep original */
  }
  return name;
}

uploadRouter.post('/pdf', upload.single('file'), async (req: AuthRequest, res: Response) => {
  const file = req.file;
  if (!file) {
    res.status(400).json({ message: '未收到文件，请选择 PDF 文件' });
    return;
  }

  try {
    const fd = fs.openSync(file.path, 'r');
    const head = Buffer.alloc(5);
    fs.readSync(fd, head, 0, 5, 0);
    fs.closeSync(fd);
    if (!head.equals(Buffer.from('%PDF-'))) {
      await unlink(file.path).catch(() => {});
      res.status(400).json({ message: '文件内容不是有效的 PDF（魔数校验失败）' });
      return;
    }
  } catch {
    await unlink(file.path).catch(() => {});
    res.status(500).json({ message: '读取上传文件失败，请重试' });
    return;
  }

  try {
    const doc = persistUploadedPdf({
      userId: req.userId!,
      originalName: file.originalname,
      sourcePath: file.path,
    });
    appendGrowthEvent(req.userId!, {
      verb: 'uploaded',
      objectType: 'document',
      objectId: doc.documentId,
      result: { original_name: doc.originalName, content_hash: doc.contentHash },
    });
    res.json({
      upload_id: doc.documentId,
      document_id: doc.documentId,
      filename: file.originalname,
    });
  } catch {
    await unlink(file.path).catch(() => {});
    res.status(500).json({ message: '保存 PDF 失败，请重试' });
  }
});

uploadRouter.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof multer.MulterError) {
    const limitMap: Record<string, string> = {
      LIMIT_FILE_SIZE: '文件不能超过 20MB',
      LIMIT_UNEXPECTED_FILE: '上传字段不正确，请选择文件',
    };
    res.status(400).json({ message: limitMap[err.code] ?? err.message });
    return;
  }
  if (err instanceof Error) {
    res.status(400).json({ message: err.message });
    return;
  }
  res.status(500).json({ message: '上传失败，请重试' });
});

interface AnalyzeBody {
  upload_id?: string;
  document_id?: string;
}

function analysisBudget(pages: Array<{ page: number; text: string }>): Array<{ page: number; text: string }> {
  const maxPagesRaw = Number(process.env.PDF_MAX_ANALYSIS_PAGES || 64);
  const maxCharsRaw = Number(process.env.PDF_MAX_ANALYSIS_CHARS || 120000);
  const maxPages = Number.isFinite(maxPagesRaw) ? Math.max(8, Math.min(200, Math.floor(maxPagesRaw))) : 64;
  const maxChars = Number.isFinite(maxCharsRaw) ? Math.max(20000, Math.min(500000, Math.floor(maxCharsRaw))) : 120000;
  if (pages.length <= maxPages && pages.reduce((sum, page) => sum + page.text.length, 0) <= maxChars) return pages;

  // 保留首页（标题/摘要）和末页（结论），中间页按原顺序截断，避免把
  // 大型论文的全部正文一次性放进 AgentRun context。
  const selected = pages.length > maxPages
    ? [...pages.slice(0, Math.max(1, maxPages - 2)), ...pages.slice(-2)]
    : [...pages];
  let remaining = maxChars;
  return selected.map((page) => {
    if (remaining <= 0) return { page: page.page, text: '' };
    const text = page.text.slice(0, remaining);
    remaining -= text.length;
    return { page: page.page, text };
  }).filter((page) => page.text.trim());
}

function pdfAgentTimeoutMs(): number {
  const configured = Number(process.env.PDF_AGENT_TIMEOUT_MS || 360000);
  return Number.isFinite(configured) ? Math.max(30_000, Math.min(configured, 480_000)) : 360000;
}

pdfRouter.post('/analyze', async (req: AuthRequest, res: Response) => {
  const body = (req.body ?? {}) as AnalyzeBody;
  const documentId = body.document_id || body.upload_id;
  if (!documentId) {
    res.status(400).json({ message: '请提供 upload_id' });
    return;
  }
  const record = loadResearchDocument(req.userId!, documentId);
  if (!record) {
    res.status(404).json({ message: '文档不存在，请重新上传' });
    return;
  }
  if (!fs.existsSync(record.storedPath)) {
    res.status(404).json({ message: '文档文件缺失，请重新上传' });
    return;
  }

  if (!agentBase()) {
    res.status(503).json({
      message: 'PDF 分析需要 A 端 Mentor Agent（MENTOR_AGENT_BASE_URL）。当前未配置，上传已保存，请启动 A 端后再点「开始分析」。',
    });
    return;
  }
  const reachable = await probeAgent(2500);
  if (!reachable) {
    res.status(503).json({
      message: `Mentor Agent 未启动或无法连接（${agentBase()}）。PDF 已保存在本服务；分析需要先启动 A 端后再点「开始分析」。`,
    });
    return;
  }

  const pages = await extractPdfPages(record.storedPath);
  const docText = pages.map((page) => page.text).join('\n');
  if (!pages.length || !docText.trim()) {
    updateResearchDocumentText(record.documentId, '', null, 'empty_text');
    res.status(422).json({
      message: '未能从 PDF 抽取正文。该文件可能是扫描件、图片 PDF 或已加密；系统不会用二进制文本或文件名冒充智能体分析结果。',
    });
    return;
  }
  if (docText && docText !== record.extractedText) {
    updateResearchDocumentText(record.documentId, docText, pages.length, docText ? 'parsed' : 'empty_text');
  }

  try {
    const pagesForAnalysis = analysisBudget(pages);
    const result = await runHarnessSkill({
      userId: req.userId!,
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
      appendGrowthEvent(req.userId!, {
        verb: 'analyze_blocked',
        objectType: 'document',
        objectId: record.documentId,
        result: { review_status: reviewStatus, run_id: result?.run_id, error: detail },
        context: { evidence_refs: result?.evidence_refs ?? [] },
        sourceRunId: isNumericRunId(String(result?.run_id || '')) ? String(result.run_id) : null,
        sourceSkillId: 'pdf_analyze',
      });
      res.status(/timeout|timed out/i.test(detail) ? 504 : 502).json({
        message: `PDF 智能体未产出通过审核的分析：${detail}`,
        run_id: result?.run_id,
        review_status: reviewStatus,
        retryable: true,
      });
      return;
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
    appendGrowthEvent(req.userId!, {
      verb: reviewStatus === 'PASS' ? 'analyzed' : 'analyze_blocked',
      objectType: 'document',
      objectId: record.documentId,
      result: { review_status: reviewStatus, run_id: result?.run_id, advisor_ids: suggestedAdvisors.map((item: any) => item.id) },
      context: { evidence_refs: result?.evidence_refs ?? [] },
      sourceRunId: isNumericRunId(String(result?.run_id || '')) ? String(result.run_id) : null,
      sourceSkillId: 'pdf_analyze',
    });
    res.json({
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
  } catch (err: any) {
    const explained = explainAgentError(err, 'PDF 分析需要 A 端 Harness，当前无法完成。');
    res.status((explained as Error & { status?: number }).status || 503).json({
      message: explained.message,
    });
  }
});

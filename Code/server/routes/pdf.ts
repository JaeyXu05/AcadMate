import { Router, Response, Request, NextFunction } from 'express';
import multer from 'multer';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { promisify } from 'util';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { persistUploadedPdf, loadResearchDocument, listResearchDocuments } from '../data/researchDocuments';
import { createPdfAnalysisJob, findActivePdfAnalysisJob, getPdfAnalysisJob, listPdfAnalysisJobs } from '../data/pdfAnalysisJobs';
import { appendGrowthEvent } from '../data/growthStore';
import { processPdfAnalysisJob, processPdfBatchAnalysisJob } from '../services/pdfAnalysis';

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

  const active = findActivePdfAnalysisJob(req.userId!, record.documentId);
  if (active) {
    res.status(202).json({
      job_id: active.jobId,
      status: active.status,
      document_id: active.documentId,
      filename: active.filename,
    });
    return;
  }
  const job = createPdfAnalysisJob(req.userId!, record.documentId, record.originalName);
  // 分析任务独立于 HTTP 请求运行；页面离开、刷新或切换路由都不会取消它。
  void processPdfAnalysisJob(job.jobId, req.userId!, record.documentId);
  res.status(202).json({
    job_id: job.jobId,
    status: job.status,
    document_id: job.documentId,
    filename: job.filename,
  });
});

interface AnalyzeBatchBody {
  upload_ids?: string[];
  document_ids?: string[];
}

pdfRouter.post('/analyze-batch', async (req: AuthRequest, res: Response) => {
  const body = (req.body ?? {}) as AnalyzeBatchBody;
  const rawIds = body.document_ids?.length ? body.document_ids : (body.upload_ids ?? []);
  const documentIds = [...new Set(rawIds.filter((id) => typeof id === 'string' && id.trim()))];
  if (documentIds.length < 2) {
    res.status(400).json({ message: '合并分析至少需要选择 2 篇 PDF' });
    return;
  }
  if (documentIds.length > 20) {
    res.status(400).json({ message: '一次合并分析最多支持 20 篇 PDF' });
    return;
  }

  for (const documentId of documentIds) {
    const record = loadResearchDocument(req.userId!, documentId);
    if (!record) {
      res.status(404).json({ message: `所选文档不存在或不属于当前用户：${documentId}` });
      return;
    }
    if (!fs.existsSync(record.storedPath)) {
      res.status(404).json({ message: `文档文件缺失，请重新上传：${record.originalName}` });
      return;
    }
  }

  const active = documentIds
    .map((documentId) => findActivePdfAnalysisJob(req.userId!, documentId))
    .find((job) => Boolean(job));
  if (active) {
    res.status(202).json({ jobs: [active] });
    return;
  }

  const jobs = documentIds.map((documentId) => {
    const record = loadResearchDocument(req.userId!, documentId)!;
    return createPdfAnalysisJob(req.userId!, documentId, record.originalName);
  });
  void processPdfBatchAnalysisJob(jobs.map((job) => job.jobId), req.userId!, documentIds);
  res.status(202).json({ jobs });
});

pdfRouter.get('/jobs', (req: AuthRequest, res: Response) => {
  res.json({ items: listPdfAnalysisJobs(req.userId!) });
});

pdfRouter.get('/documents', (req: AuthRequest, res: Response) => {
  res.json({ items: listResearchDocuments(req.userId!) });
});

pdfRouter.get('/jobs/:jobId', (req: AuthRequest, res: Response) => {
  const job = getPdfAnalysisJob(req.userId!, req.params.jobId);
  if (!job) {
    res.status(404).json({ message: '分析任务不存在' });
    return;
  }
  res.json(job);
});

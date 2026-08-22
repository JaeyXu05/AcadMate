import { Router, Response, Request, NextFunction } from 'express';
import multer from 'multer';
import path from 'path';
import os from 'os';
import fs from 'fs';
import { promisify } from 'util';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toLightAdvisor } from '../data/ragAdvisors';
import {
  extractPdfText,
  rankCandidatesByContent,
  inferTopicsFromMatches,
  buildSummary,
  buildKeyPoints,
} from './pdfText';

const unlink = promisify(fs.unlink);

export const pdfRouter = Router();
export const uploadRouter = Router();

pdfRouter.use(authMiddleware);
uploadRouter.use(authMiddleware);

// ---- [STUB] PDF 上传与分析 ----
// 队友 A（检索智能体）交付后：
//   1) 把 POST /pdf/analyze 的实现替换为真实文档解析 + 智能体分析，
//      保持响应契约 { summary, keyPoints, suggestedAdvisors } 不变，前端零改动；
//   2) 上传端点 POST /upload/pdf 可保留（仅落地文件并返回 upload_id），分析逻辑替换即可。
// 当前分析结果为基于文件名的确定性假数据，不实际解析 PDF 内容。

// 内存中登记上传：upload_id → { filename, originalname, userId, uploadedAt }
interface UploadRecord {
  filename: string;
  originalname: string;
  userId: number;
  uploadedAt: number;
}
const UPLOADS = new Map<string, UploadRecord>();

/** upload_id 有效期：30 分钟内未分析的记录视为过期，避免内存 Map 无限增长（用户上传后未分析即关闭页面）。 */
const UPLOAD_TTL_MS = 30 * 60 * 1000;

/** 清扫过期的上传记录（在每次上传时顺带执行，惰性回收），同时删除已过期的临时文件。 */
async function sweepExpiredUploads(): Promise<void> {
  const now = Date.now();
  for (const [id, rec] of UPLOADS) {
    if (now - rec.uploadedAt > UPLOAD_TTL_MS) {
      UPLOADS.delete(id);
      // 未及时分析的临时 PDF 一并清掉，避免堆积
      void unlink(path.join(os.tmpdir(), rec.filename)).catch(() => {});
    }
  }
}

// multer 落地到系统临时目录，文件名用 时间戳-随机串 避免冲突
const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, os.tmpdir()),
  filename: (_req, file, cb) => {
    const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
    cb(null, `pdf-${unique}${path.extname(file.originalname) || '.pdf'}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: 20 * 1024 * 1024 }, // 20MB
  fileFilter: (_req, file, cb) => {
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

/** POST /api/upload/pdf — 上传 PDF，返回 upload_id（stub 仅落地文件，不做分析） */
uploadRouter.post('/pdf', upload.single('file'), async (req: AuthRequest, res: Response) => {
  const file = req.file;
  if (!file) {
    res.status(400).json({ message: '未收到文件，请选择 PDF 文件' });
    return;
  }

  // 魔数嗅探：只凭扩展名/MIME 不可靠（可伪造），读文件头确认是真正的 PDF（%PDF-）。
  // 这里在临时文件落地（磁盘路径 file.path）后同步读前几字节校验，非 PDF 则删掉临时文件拒绝。
  try {
    const fd = fs.openSync(file.path, 'r');
    const head = Buffer.alloc(5);
    fs.readSync(fd, head, 0, 5, 0);
    fs.closeSync(fd);
    if (!head.equals(Buffer.from('%PDF-'))) {
      await unlink(file.path).catch(() => {}); // 清理：不是真 PDF 时不留垃圾临时文件
      res.status(400).json({ message: '文件内容不是有效的 PDF（魔数校验失败）' });
      return;
    }
  } catch {
    await unlink(file.path).catch(() => {});
    res.status(500).json({ message: '读取上传文件失败，请重试' });
    return;
  }

  const upload_id = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
  await sweepExpiredUploads(); // 惰性回收过期记录，防止未分析的上传长期堆积
  UPLOADS.set(upload_id, {
    filename: file.filename,
    originalname: file.originalname,
    userId: req.userId!,
    uploadedAt: Date.now(),
  });
  res.json({ upload_id, filename: file.originalname });
});

/**
 * multer 错误处理中间件：把 multer 抛出的文件类型/大小错误转为统一 JSON 响应，
 * 否则 Express 默认返回 HTML 错误页，前端 axios 无法解析。
 * 必须挂在 /upload/pdf 路由之后。
 */
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
    // fileFilter 抛出的"仅支持 PDF 文件"等自定义错误
    res.status(400).json({ message: err.message });
    return;
  }
  res.status(500).json({ message: '上传失败，请重试' });
});

interface AnalyzeBody {
  upload_id?: string;
}

/** POST /api/pdf/analyze — 分析已上传的 PDF（真实文本抽取 + 内容匹配） */
pdfRouter.post('/analyze', async (req: AuthRequest, res: Response) => {
  const { upload_id } = (req.body ?? {}) as AnalyzeBody;
  if (!upload_id) {
    res.status(400).json({ message: '请提供 upload_id' });
    return;
  }
  const record = UPLOADS.get(upload_id);
  if (!record) {
    res.status(404).json({ message: '上传记录不存在或已过期，请重新上传' });
    return;
  }
  // 简单的归属校验：upload_id 必须属于当前用户
  if (record.userId !== req.userId) {
    res.status(403).json({ message: '无权分析该文件' });
    return;
  }

  const filePath = path.join(os.tmpdir(), record.filename);
  const candidates = ragStore.getCandidates();

  // ---- 1) 抽取 PDF 全文 ----
  let docText = '';
  try {
    docText = await extractPdfText(filePath);
  } catch {
    docText = '';
  }

  // ---- 2) 基于内容匹配导师（若文本为空则回退整库给定序推荐）----
  const contentMatches = rankCandidatesByContent(candidates, docText);
  const topics = inferTopicsFromMatches(contentMatches, candidates);

  let picks: typeof candidates;
  let matchedTerms: string[][] = [];
  if (contentMatches.length) {
    picks = contentMatches.slice(0, 3).map((m) => candidates[m.index]);
    matchedTerms = contentMatches.slice(0, 3).map((m) => m.matchedTerms);
  } else {
    // 无文本可匹配：按论文数取前 3 支确定性导师，保证仍能出结果
    picks = candidates
      .slice()
      .sort((a, b) => (Array.isArray(b.publications) ? b.publications.length : 0) - (Array.isArray(a.publications) ? a.publications.length : 0))
      .slice(0, 3);
    matchedTerms = picks.map(() => []);
  }

  const suggestedAdvisors = picks
    .map((c, i) => {
      const terms = matchedTerms[i] ?? [];
      return {
        ...toLightAdvisor(c),
        matchScore: 60 + Math.min(35, Math.round((contentMatches[i]?.score ?? 0) / 2)),
        explanation: terms.length
          ? `检测到文档关键词「${terms.slice(0, 3).join('、')}」，与 ${c.mentor_name} 的研究方向「${(Array.isArray(c.research_topics) ? c.research_topics : []).slice(0, 2).join('、') || '相关领域'}」匹配。`
          : `${c.mentor_name} 在「${(Array.isArray(c.research_topics) ? c.research_topics : []).slice(0, 2).join('、') || '相关领域'}」方向可能与你上传的文档兴趣相符。`,
      };
    })
    .sort((a, b) => b.matchScore - a.matchScore);

  const summary = buildSummary(docText, topics, record.originalname, suggestedAdvisors.length);
  const keyPoints = buildKeyPoints(docText, topics, contentMatches, candidates);

  // ---- 3) 清理临时文件 + 移除登记 ----
  UPLOADS.delete(upload_id);
  void unlink(filePath).catch(() => {
    // 文件可能已被系统/其他清理移除，忽略
  });

  res.json({ summary, keyPoints, suggestedAdvisors });
});

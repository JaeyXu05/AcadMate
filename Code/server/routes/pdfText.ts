/**
 * PDF 文本抽取 + 内容分析（D 侧）。
 *
 * 替换原 pdf.ts 里基于文件名的确定性 stub —— 真正读取 PDF 的文本内容，
 * 据此生成全文总结（summary）和关键要点（keyPoints）。导师检索由 A 端
 * pdf_analyze 的结构化语义链完成，本文件不再反向借导师标签推断 PDF 主题。
 *
 * 文本抽取用 `unpdf`（服务端对 pdfjs-dist 的封装，无原生依赖）。
 * 总结/要点只消费 A 端智能体通过结构化审核的结果；文本抽取失败时
 * 返回空页，不再把 PDF 二进制中的可打印字符冒充论文正文。
 */

import fs from 'fs';

// unpdf 是 ESM + CJS 双发；只初始化一次，避免每个请求重复解析模块。
// 注意：unpdf 的 `extractText` 在本环境会走 Playwright 分支而抽不到文本，
// 故改用更底层的 `getDocumentProxy` + 逐页 `getTextContent`（pdfjs 直连）。
type GetDocumentProxy = (data: Uint8Array) => Promise<any>;
let getDocumentProxyPromise: Promise<GetDocumentProxy | null> | null = null;

async function loadGetDocumentProxy(): Promise<GetDocumentProxy | null> {
  if (!getDocumentProxyPromise) {
    getDocumentProxyPromise = import('unpdf')
      .then((module) => typeof module.getDocumentProxy === 'function' ? module.getDocumentProxy as GetDocumentProxy : null)
      .catch(() => null);
  }
  return getDocumentProxyPromise;
}

/** 读取 PDF 文件提取纯文本（失败返回空串，调用方据此降级） */
export async function extractPdfText(filePath: string): Promise<string> {
  const pages = await extractPdfPages(filePath);
  return pages.map((page) => page.text).join('\n').replace(/\s+/g, ' ').trim();
}

export interface PdfPageText {
  page: number;
  text: string;
}

export async function extractPdfPages(filePath: string): Promise<PdfPageText[]> {
  try {
    const getDocumentProxy = await loadGetDocumentProxy();
    if (!getDocumentProxy) {
      throw new Error('unpdf 缺少 getDocumentProxy');
    }
    const buf = await fs.promises.readFile(filePath);
    const doc = await getDocumentProxy(new Uint8Array(buf));
    const pages: PdfPageText[] = [];
    for (let i = 1; i <= doc.numPages; i += 1) {
      const page = await doc.getPage(i);
      const tc = await page.getTextContent();
      const text = (tc?.items ?? [])
        .map((it: any) => ('str' in it ? it.str : ''))
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim();
      if (text) pages.push({ page: i, text });
    }
    return pages;
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// 分词 / 关键词提取
// ---------------------------------------------------------------------------

/** 从文本里按空格/标点切出中文短语（用于中文文档的主题词），返回高频词 */
function extractCjkTerms(text: string): Map<string, number> {
  const freq = new Map<string, number>();
  const runs = text.match(/[一-鿿]{2,16}/g) ?? [];
  for (const r of runs) {
    freq.set(r, (freq.get(r) ?? 0) + 1);
    if (r.length >= 2) {
      for (let i = 0; i <= r.length - 2; i += 1) {
        const bigram = r.slice(i, i + 2);
        freq.set(bigram, (freq.get(bigram) ?? 0) + 1);
      }
    }
  }
  return freq;
}

export interface ContentMatch {
  index: number;
  score: number;
  matchedTerms: string[];
}

interface CandidateSummary {
  mentor_name: string;
  department?: string;
  research_topics?: string[];
}

/** A 端 pdf_analyze Harness 返回的结构化文档分析。 */
export interface StructuredPdfAnalysis {
  document_summary?: unknown;
  research_directions?: unknown;
  methods?: unknown;
}

function analysisList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => String(item ?? '').trim())
    .filter(Boolean);
}

/** 生成一段可读的全文总结 */
export function buildSummary(
  docText: string,
  topics: string[],
  filename: string,
  matchCount: number,
  options?: { reviewStatus?: string; analysis?: StructuredPdfAnalysis },
): string {
  const structuredSummary = typeof options?.analysis?.document_summary === 'string'
    ? options.analysis.document_summary.trim()
    : '';
  if (structuredSummary) {
    return structuredSummary;
  }

  const leading = docText.replace(/\s+/g, ' ').trim().slice(0, 260);
  if (!leading) {
    return '未能抽出可检索正文（扫描件、图片 PDF 或加密文档）。本次不会按文件名或论文数推荐导师。';
  }
  if (options?.reviewStatus === 'REVISE' || matchCount === 0) {
    return `该文档摘要：${leading}${leading.length >= 260 ? '…' : ''}\n\n已抽出正文，但没有与导师研究方向重叠的页级证据，因此不生成推荐名单。`;
  }
  return `该文档摘要：${leading}${leading.length >= 260 ? '…' : ''}\n\n已返回 ${matchCount} 位候选导师；详情以页级证据和审核结果为准。`;
}

/** 生成关键要点（从实际内容归纳，而非固定模板） */
export function buildKeyPoints(
  docText: string,
  topics: string[],
  matches: ContentMatch[],
  candidates: CandidateSummary[],
  options?: {
    reviewStatus?: string;
    advisors?: Array<{ name?: string; explanation?: string }>;
    error?: string;
    analysis?: StructuredPdfAnalysis;
  },
): string[] {
  const points: string[] = [];
  if (options?.error) points.push(String(options.error));
  if (!docText.trim()) {
    points.push('没有可引用的页级文本，拒绝生成导师名单。');
    return points;
  }

  const structuredDirections = analysisList(options?.analysis?.research_directions);
  const structuredMethods = analysisList(options?.analysis?.methods);
  if (structuredDirections.length) {
    points.push(`研究方向：${structuredDirections.slice(0, 4).join('、')}`);
  } else if (topics.length) {
    points.push(`研究方向：${topics.slice(0, 4).join('、')}`);
  }
  if (structuredMethods.length) {
    points.push(`研究方法：${structuredMethods.slice(0, 4).join('、')}`);
  }

  // 结构化分析存在时，不再把 PDF 页眉、模型名、尺寸和指标当成主题词。
  if (!options?.analysis) {
    const shared = new Set(matches.slice(0, 4).flatMap((m) => m.matchedTerms));
    if (shared.size) {
      points.push(`核心关键词：${[...shared].slice(0, 8).join('、')}`);
    }
    const cjk = extractCjkTerms(docText);
    const topCjk = [...cjk.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k]) => k);
    if (topCjk.length) {
      points.push(`文档高频主题词：${topCjk.join('、')}`);
    }
  }
  for (const advisor of (options?.advisors ?? []).slice(0, 3)) {
    if (advisor.explanation) points.push(String(advisor.explanation));
  }
  const best = matches[0];
  if (best && candidates[best.index]) {
    const c = candidates[best.index];
    points.push(
      `与文档内容最匹配的导师是「${c.mentor_name}」（${c.department ?? '院系未知'}），研究方向「${(Array.isArray(c.research_topics) ? c.research_topics : []).slice(0, 3).join('、') || '—'}」。`,
    );
  }
  if (points.length === 0) {
    points.push('未能从文档中提取到明确的主题信息，建议检查 PDF 是否为文字版。');
  }
  return points;
}

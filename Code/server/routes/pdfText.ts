/**
 * PDF 文本抽取 + 内容分析（D 侧）。
 *
 * 替换原 pdf.ts 里基于文件名的确定性 stub —— 真正读取 PDF 的文本内容，
 * 据此生成全文总结（summary）、关键要点（keyPoints），并按「文档关键词 ↔ 导师
 * research_topics / publications」的命中程度推荐导师。这样 PDF 分析结果反映的
 * 是文档实际内容，而不是文件名长度。
 *
 * 文本抽取用 `unpdf`（服务端对 pdfjs-dist 的封装，无原生依赖）。
 * 总结/要点为确定性启发式（离线模式无模型 key，不调用 LLM），保证可复现。
 */

import fs from 'fs';
import type { RagMentor } from '../data/ragAdvisors';

// unpdf 是 ESM + CJS 双发；server 以 tsx 运行 ESM。
// 注意：unpdf 的 `extractText` 在本环境会走 Playwright 分支而抽不到文本，
// 故改用更底层的 `getDocumentProxy` + 逐页 `getTextContent`（pdfjs 直连，已验证可抽到）。
type TextExtractor = (src: string | Uint8Array) => Promise<string>;
let extractText: TextExtractor | null = null;
async function loadUnpdf(): Promise<TextExtractor> {
  if (extractText) return extractText;
  try {
    const { getDocumentProxy } = (await import('unpdf')) as {
      getDocumentProxy?: (data: Uint8Array) => Promise<any>;
    };
    if (typeof getDocumentProxy !== 'function') {
      throw new Error('unpdf 缺少 getDocumentProxy');
    }
    extractText = async (src) => {
      const buf = typeof src === 'string' ? fs.readFileSync(src) : new Uint8Array(src);
      const doc = await getDocumentProxy(new Uint8Array(buf));
      let parts: string[] = [];
      for (let i = 1; i <= doc.numPages; i++) {
        const page = await doc.getPage(i);
        const tc = await page.getTextContent();
        const pageText = (tc?.items ?? [])
          .map((it: any) => ('str' in it ? it.str : ''))
          .join(' ');
        parts.push(pageText);
      }
      return parts.join('\n').replace(/\s+/g, ' ').trim();
    };
    return extractText;
  } catch {
    // unpdf 未安装/调用异常时回退到轻量解析，避免 PDF 功能崩溃
    extractText = fallbackExtractText;
    return extractText;
  }
}

/** 后备：仅抽取流内可读文本（非常粗糙，仅应急）。 */
async function fallbackExtractText(src: string | Uint8Array): Promise<string> {
  const buf = typeof src === 'string' ? fs.readFileSync(src) : Buffer.from(src);
  const raw = buf.toString('latin1');
  // 去掉二进制，只保留可打印 ASCII/中文片段
  const cleaned = raw.replace(/[^\x20-\x7e一-鿿\n\r\t]/g, ' ');
  return cleaned.replace(/\s+/g, ' ').trim();
}

/** 读取 PDF 文件提取纯文本（失败返回空串，调用方据此降级） */
export async function extractPdfText(filePath: string): Promise<string> {
  const fn = await loadUnpdf();
  try {
    const text = await fn(filePath);
    return (text ?? '').trim();
  } catch {
    return '';
  }
}

// ---------------------------------------------------------------------------
// 分词 / 关键词提取
// ---------------------------------------------------------------------------

const STOPWORDS = new Set(
  'the a an of and or to in for on with by at from as is are was were be been being this that these those it its do does did done has have had not no but if then than so such can could will would may might must shall should about into over under between through etc ie eg via using use used based upon our their them his her its'.split(' '),
);

/** 从文本提取有意义的英文词干（小写、去停用、去标点），附频次 */
function extractTerms(text: string): Map<string, number> {
  const freq = new Map<string, number>();
  const tokens = text.toLowerCase().match(/[a-z][a-z0-9-]{2,}/g) ?? [];
  for (const t of tokens) {
    const w = t.replace(/^-+|-+$/g, '');
    if (!w || w.length < 3 || STOPWORDS.has(w) || /^\d+$/.test(w)) continue;
    freq.set(w, (freq.get(w) ?? 0) + 1);
  }
  return freq;
}

/** 把一个候选导师展开成可检索的文本（研究方向 + 论文标题） */
function mentorText(c: RagMentor): string {
  const topics = Array.isArray(c.research_topics) ? c.research_topics.join(' ') : '';
  const pubs = Array.isArray(c.publications) ? c.publications.join(' ') : '';
  return `${topics} ${pubs} ${c.mentor_name ?? ''}`;
}

export interface ContentMatch {
  index: number;
  score: number;
  matchedTerms: string[];
}

/** 用文档词频在候选导师中打分，返回按分数降序的匹配结果 */
export function rankCandidatesByContent(
  candidates: RagMentor[],
  docText: string,
): ContentMatch[] {
  const docTerms = extractTerms(docText);
  if (docTerms.size === 0) return [];

  const matches: ContentMatch[] = [];
  candidates.forEach((c, index) => {
    const cTerms = extractTerms(mentorText(c));
    if (cTerms.size === 0) return;
    let score = 0;
    const matched: string[] = [];
    for (const [term, count] of docTerms) {
      if (cTerms.has(term)) {
        score += count * (cTerms.get(term) ?? 1);
        matched.push(term);
      }
    }
    if (score > 0) matches.push({ index, score, matchedTerms: matched.slice(0, 8) });
  });
  matches.sort((a, b) => b.score - a.score);
  return matches;
}

/** 从匹配到的导师关键词里汇总文档最可能的领域主题 */
export function inferTopicsFromMatches(matches: ContentMatch[], candidates: RagMentor[]): string[] {
  const topicCount = new Map<string, number>();
  for (const m of matches.slice(0, 6)) {
    const c = candidates[m.index];
    for (const t of Array.isArray(c.research_topics) ? c.research_topics : []) {
      topicCount.set(t, (topicCount.get(t) ?? 0) + m.score);
    }
  }
  return [...topicCount.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([t]) => t)
    .filter(Boolean);
}

/** 从文本里按空格/标点切出中文短语（用于中文文档的主题词），返回高频词 */
function extractCjkTerms(text: string): Map<string, number> {
  const freq = new Map<string, number>();
  const runs = text.match(/[一-鿿]{2,16}/g) ?? [];
  for (const r of runs) {
    freq.set(r, (freq.get(r) ?? 0) + 1);
  }
  return freq;
}

/** 生成一段可读的全文总结 */
export function buildSummary(docText: string, topics: string[], filename: string, matchCount: number): string {
  const leading = docText
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 260);
  const topicPhrase = topics.length ? topics.slice(0, 3).join('」、「') : '相关研究方向';
  const intro = leading
    ? `该文档摘要：${leading}${leading.length >= 260 ? '…' : ''}`
    : '未能抽取到可用的正文文本（可能是扫描版或纯图片 PDF），仅能按文件名给出推荐。';
  return `${intro}\n\n根据对全文关键词的分析，本文主题与「${topicPhrase}」等方向高度相关，已据此为你匹配 ${matchCount} 位研究方向相近的导师。`;
}

/** 生成关键要点（从实际内容归纳，而非固定模板） */
export function buildKeyPoints(
  docText: string,
  topics: string[],
  matches: ContentMatch[],
  candidates: RagMentor[],
): string[] {
  const points: string[] = [];
  if (topics.length) {
    points.push(`研究方向：${topics.slice(0, 4).join('、')}`);
  }
  // 词频最高、且在候选导师中出现过的主题词作为「核心关键词」
  const shared = new Set(matches.slice(0, 4).flatMap((m) => m.matchedTerms));
  if (shared.size) {
    points.push(`核心关键词：${[...shared].slice(0, 8).join('、')}`);
  }
  // 中文主题词（若命中）
  const cjk = extractCjkTerms(docText);
  const topCjk = [...cjk.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k]) => k);
  if (topCjk.length) {
    points.push(`文档高频主题词：${topCjk.join('、')}`);
  }
  // 最佳匹配导师
  const best = matches[0];
  if (best) {
    const c = candidates[best.index];
    points.push(
      `与文档内容最匹配的导师是「${c.mentor_name}」（${c.department ?? '院系未知'}），研究方向「${(Array.isArray(c.research_topics) ? c.research_topics : []).slice(0, 3).join('、') || '—'}」。`,
    );
  }
  // 兜底：确保至少有一两条
  if (points.length === 0) {
    points.push('未能从文档中提取到明确的主题信息，建议检查 PDF 是否为文字版。');
  }
  return points;
}

/**
 * 精确主题重叠打分（与 A 后端 `evaluation.py::_overlap_score` 同源）。
 *
 * 让「猜你喜欢」与「导师检索」共用同一套研究方向匹配口径：把查询主题与候选
 * 研究方向做词元级重叠，得到校准后的 0-100 匹配分，而不是靠 substring 命中数
 * 或向量余弦换算的分数。这样推荐页的分与检索页的分含义一致、可直接比较。
 *
 * 词元化与后端一致：英文词（len>=2）+ 中文整短语 + 中文二元组。整词精确命中=1.0，
 * "深度强化学习" vs "强化学习" 这类近义变换靠二元组共享片段给出足够高的分。
 */

const CJK = /[一-鿿]/g;

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').trim();
}

function tokens(value: string): string[] {
  const text = value.toLowerCase();
  const result: string[] = [];
  // 英文词
  for (const word of text.match(/[a-z0-9][a-z0-9\-\.]*/g) ?? []) {
    if (word.length >= 2) result.push(word);
  }
  // 中文整短语 + 二元组
  const chars = text.match(CJK) ?? [];
  if (chars.length > 0) {
    result.push(chars.join(''));
    for (let i = 0; i < chars.length - 1; i++) {
      result.push(chars[i] + chars[i + 1]);
    }
  }
  return result;
}

/** query 与候选集合中某一项的 token 级 Jaccard 重叠，取最大值。 */
function contained(query: string, available: string[]): number {
  const queryTokens = new Set(tokens(query));
  if (queryTokens.size === 0) return 0;
  let best = 0;
  for (const item of available) {
    if (!item) continue;
    const itemTokens = new Set(tokens(item));
    if (itemTokens.size === 0) continue;
    let overlap = 0;
    for (const t of itemTokens) if (queryTokens.has(t)) overlap++;
    const score = overlap / queryTokens.size;
    if (score > best) best = score;
  }
  return best;
}

/**
 * 校准后的研究方向匹配分（0-100）。逐条查询项，取它在候选方向里的最高词元重
 * 叠度再取均值；候选/查询为空按 0 处理。
 */
export function topicOverlapScore(
  requested: string[],
  available: string[],
): number {
  if (!requested || requested.length === 0) return 0;
  const normalizedAvailable = (available ?? []).map(normalize);
  const perItem: number[] = [];
  for (const raw of requested) {
    const q = normalize(raw ?? '');
    if (!q) {
      perItem.push(0);
      continue;
    }
    let best = contained(q, normalizedAvailable);
    if (normalizedAvailable.includes(q)) {
      best = 1.0; // 整词精确命中
    } else if (best <= 0 && normalizedAvailable.some((a) => a.includes(q))) {
      best = 1.0; // 兼容含标点的长句内联子串命中
    }
    perItem.push(best);
  }
  if (perItem.length === 0) return 0;
  return Math.round((100 * perItem.reduce((s, x) => s + x, 0)) / perItem.length);
}

/** 返回查询集合里与候选某方向精确（归一化后相等）命中的子集。 */
export function topicOverlap(
  requested: string[],
  available: string[],
): string[] {
  const normalizedAvailable = new Set((available ?? []).map(normalize));
  return (requested ?? []).filter((item) =>
    normalizedAvailable.has(normalize(item)),
  );
}

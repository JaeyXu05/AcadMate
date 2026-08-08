import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toLightAdvisor, RagMentor } from '../data/ragAdvisors';

export const recommendRouter = Router();

recommendRouter.use(authMiddleware);

// ---- 猜你喜欢（基于个人画像 + 真实 RAG 导师数据）----
// 响应契约 Advisor[] 不变，前端零改动。
// 用个人画像（interests/skills）关键词与 715 位真实导师的
// research_topics 做匹配 + 学术指标兜底排序，返回确定性结果。

/** 取当前用户 profile（用于兴趣匹配） */
function getUserProfile(userId: number) {
  const db = getDb();
  return db
    .prepare('SELECT nickname, interests, skills FROM users WHERE id = ?')
    .get(userId) as
    | { nickname: string; interests: string; skills: string }
    | undefined;
}

/** 安全解析 SQLite 中的 JSON 字符串数组字段 */
function safeParseArray(val: string | undefined | null): string[] {
  if (!val) return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** 计算导师与一组兴趣关键词的命中数（确定性，无随机） */
function matchScore(c: RagMentor, keywords: string[]): number {
  if (keywords.length === 0) return 0;
  const haystack = [
    c.mentor_name,
    ...(c.research_topics ?? []),
    ...(c.methods ?? []),
    c.department ?? '',
  ]
    .join(' ')
    .toLowerCase();
  let hits = 0;
  for (const kw of keywords) {
    const k = (kw || '').trim().toLowerCase();
    if (k && haystack.includes(k)) {
      hits += 1;
    }
  }
  return hits;
}

/** GET /api/recommend — 基于个人画像推荐导师 */
recommendRouter.get('/', (req: AuthRequest, res: Response) => {
  if (!ragStore.getCandidates().length) {
    res.status(503).json({ message: '导师数据源不可用，请确认 RAG 数据已生成' });
    return;
  }

  const user = getUserProfile(req.userId!);
  const interests = safeParseArray(user?.interests);
  const skills = safeParseArray(user?.skills);
  const keywords = [...interests, ...skills].map((s) => s.trim()).filter(Boolean);

  // 给每位导师算命中数，按命中数降序；同命中按论文数降序；再按 id 兜底
  const ranked = ragStore
    .getCandidates()
    .map((c) => {
      const hits = matchScore(c, keywords);
      const papers = Array.isArray(c.publications) ? c.publications.length : 0;
      return { c, hits, papers };
    })
    .sort((x, y) => {
      if (y.hits !== x.hits) return y.hits - x.hits;
      if (y.papers !== x.papers) return y.papers - x.papers;
      return x.c.candidate_id.localeCompare(y.c.candidate_id);
    });

  // 推荐结果：取前 6 位。命中兴趣的导师 matchScore 抬高，未命中的兜底导师给较低分，
  // 保证命中的明显靠前且区分度清晰。
  const result = ranked.slice(0, 6).map(({ c, hits }) => {
    const light = toLightAdvisor(c);
    let finalScore: number;
    if (hits > 0) {
      finalScore = Math.min(95, 78 + hits * 6);
    } else {
      const papers = light.papers;
      // 兜底：论文多的导师分略高，区间 55~72
      finalScore = Math.round(Math.min(72, 55 + Math.log2(papers + 1) * 3));
      if (finalScore < 50) finalScore = 50;
      if (finalScore > 72) finalScore = 72;
    }
    return {
      ...light,
      matchScore: finalScore,
      explanation:
        hits > 0
          ? `你的兴趣「${keywords.slice(0, 3).join('、')}」与${c.mentor_name}的研究方向「${(c.research_topics ?? []).slice(0, 3).join('、')}」相关，命中 ${hits} 个方向`
          : `根据综合学术指标推荐${c.mentor_name}，研究方向「${(c.research_topics ?? []).slice(0, 3).join('、') || '见导师详情'}」`,
    };
  });

  res.json({ recommendations: result, basedOn: keywords });
});
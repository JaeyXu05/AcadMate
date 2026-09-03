import { getDb } from '../db';
import { loadGrowthState, loadUserProfile } from './growthStore';
import { ragStore } from './ragAdvisors';
import { cleanTopics } from './topicBoilerplate';
import { isGenericParentTerm, longTermInterestTerms, sessionInterestTerms } from './mentorRetrieval';

export interface RecommendMemory {
  longTerm: string[];
  recent: string[];
  core: string[];
}

function uniqueCap(items: string[], cap: number): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const key = item.toLowerCase();
    if (!item || seen.has(key)) continue;
    seen.add(key);
    result.push(item);
    if (result.length >= cap) break;
  }
  return result;
}

function favoriteDirectionHints(userId: number): string[] {
  const ids = (getDb()
    .prepare('SELECT advisor_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC LIMIT 8')
    .all(userId) as Array<{ advisor_id: string }>)
    .map((row) => row.advisor_id);
  const hints: string[] = [];
  for (const id of ids) {
    const mentor = ragStore.getById(id);
    const topic = cleanTopics(mentor?.research_topics, mentor?.mentor_name)
      .find((item) => !isGenericParentTerm(item));
    if (topic) hints.push(topic);
  }
  return hints;
}

function recentSearchQueries(userId: number, limit = 2): string[] {
  const rows = getDb()
    .prepare(
      `SELECT query FROM search_history WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 12`,
    )
    .all(userId) as Array<{ query: string }>;
  const seen = new Set<string>();
  const queries: string[] = [];
  for (const row of rows) {
    const query = String(row.query || '').trim();
    const key = query.toLowerCase();
    if (!query || seen.has(key)) continue;
    seen.add(key);
    queries.push(query);
    if (queries.length >= limit) break;
  }
  return queries;
}

/** 猜你喜欢主信号：长期核心方向 + 最近 1–2 次检索，不是全历史并集。 */
export function loadRecommendMemory(userId: number): RecommendMemory {
  const profile = loadUserProfile(userId);
  const growth = loadGrowthState(userId);
  const interests = Array.isArray(profile.interests) ? profile.interests.map(String) : [];
  const longTerm = uniqueCap(
    longTermInterestTerms([...growth.directions, ...interests, ...favoriteDirectionHints(userId)]),
    8,
  );
  const recent = uniqueCap(sessionInterestTerms(recentSearchQueries(userId, 2)), 2);
  const core = uniqueCap([...longTerm, ...recent], 8);
  return { longTerm, recent, core };
}

export function studentIdentity(userId: number): {
  name: string;
  email: string;
  grade: string;
  major: string;
  education: string;
} {
  const row = getDb()
    .prepare('SELECT email, nickname, grade, major FROM users WHERE id = ?')
    .get(userId) as { email?: string; nickname?: string; grade?: string; major?: string } | undefined;
  const email = String(row?.email || '').trim();
  const nickname = String(row?.nickname || '').trim();
  const grade = String(row?.grade || '').trim();
  const major = String(row?.major || '').trim();
  // 邮箱前缀不是学生姓名；没有填写昵称时应跳过姓名相关内容，
  // 避免把 xjy230702 之类的登录标识写进套磁信。
  const name = nickname;
  const education = [grade, major].filter(Boolean).join(' / ');
  return { name, email, grade, major, education };
}

export function verifiedPaperTitles(userId: number, advisorId: string): string[] {
  const titles: string[] = [];
  const growth = loadGrowthState(userId);
  for (const raw of growth.read_papers) {
    if (!raw || typeof raw !== 'object') continue;
    const item = raw as Record<string, unknown>;
    if (String(item.candidate_id ?? '') !== advisorId) continue;
    const list = Array.isArray(item.titles) ? item.titles : [];
    for (const title of list) {
      const text = String(title || '').trim();
      if (text) titles.push(text);
    }
  }
  return uniqueCap(titles, 5);
}

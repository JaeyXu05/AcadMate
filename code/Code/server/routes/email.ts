import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, toAdvisorDetail } from '../data/ragAdvisors';

export const emailRouter = Router();

emailRouter.use(authMiddleware);

// ---- 邮件生成（真实 RAG 导师数据）----
// 按前端契约 { subject, body } 返回，前端零改动。
// 用模板字符串 + RAG 导师详情 + 当前用户 profile 生成申请意向邮件。
// （若队友 A 交付 generate_email_template 工具，可替换实现，契约不变。）

interface EmailRequestBody {
  advisor_id?: string;
}

/** 取当前用户 profile（用于邮件自我介绍） */
function getUserProfile(userId: number) {
  const db = getDb();
  return db
    .prepare('SELECT nickname, grade, major, interests, skills, bio FROM users WHERE id = ?')
    .get(userId) as
    | { nickname: string; grade: string; major: string; interests: string; skills: string; bio: string }
    | undefined;
}

/** 拼接"年级 + 专业"作为身份前缀，缺失字段优雅省略 */
function buildIdentity(grade: string, major: string): string {
  const parts = [grade, major].filter(Boolean);
  return parts.length > 0 ? parts.join('·') : '';
}

/** 拼接研究兴趣 + 技能为背景描述，缺失则返回空串 */
function buildBackground(interests: string[], skills: string[]): string {
  const lines: string[] = [];
  if (interests.length > 0) {
    lines.push(`研究兴趣：${interests.join('、')}`);
  }
  if (skills.length > 0) {
    lines.push(`技能基础：${skills.join('、')}`);
  }
  return lines.length > 0 ? '\n' + lines.map((l) => `  · ${l}`).join('\n') : '';
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

/** POST /api/email/generate — 生成联系导师邮件 */
emailRouter.post('/generate', (req: AuthRequest, res: Response) => {
  const { advisor_id } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id) {
    res.status(400).json({ message: '请提供 advisor_id' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  if (!candidate) {
    res.status(404).json({ message: '未找到该导师' });
    return;
  }
  const advisor = toAdvisorDetail(candidate);

  const user = getUserProfile(req.userId!);
  const nickname = (user?.nickname || '').trim() || '同学';
  const grade = (user?.grade || '').trim();
  const major = (user?.major || '').trim();
  const interests = safeParseArray(user?.interests);
  const skills = safeParseArray(user?.skills);
  const identity = buildIdentity(grade, major);

  // 主题：申请意向 + 姓名 + 身份
  const subjectParts = ['研究生申请', nickname];
  if (identity) subjectParts.push(identity);
  const subject = subjectParts.join('—');

  // 代表论文引用（使对导师研究的了解具体、不空泛）
  const paper = advisor.recentPapers?.[0];
  const paperRef = paper
    ? `您近期发表的《${paper.title}》${paper.venue ? `（${paper.venue}${paper.year ? `, ${paper.year}` : ''}）` : ''}`
    : `您在${advisor.tags.slice(0, 2).join('、')}方向的工作`;

  // 与导师方向的兴趣交集（若有）
  const advisorTagSet = new Set(advisor.tags);
  const overlap = interests.filter((i) => advisorTagSet.has(i));
  const background = buildBackground(interests, skills);
  const fitSentence = overlap.length > 0
    ? `我的研究兴趣中${overlap.join('、')}与您的方向较为契合，`
    : '';

  const body = `尊敬的${advisor.name}老师：

您好！${identity ? `我是${identity}的${nickname}，` : `我叫${nickname}，`}计划申请研究生，对您在${advisor.tags.slice(0, 2).join('、')}方向的研究非常感兴趣。

我阅读了${paperRef}，对其中${overlap.length > 0 ? `与${overlap.join('、')}相关的` : ''}思路印象深刻，也由此希望能在该方向上继续深入。${fitSentence}若有幸加入您的课题组，我愿意尽快融入并承担具体工作。${background ? `我的相关背景如下：${background}\n` : ''}冒昧打扰，想请教您近期是否有硕士或博士招生名额？附件是我的简历与成绩单，如方便，期待有机会与您进一步交流。

感谢您在百忙之中阅读此信。

此致
敬礼

${nickname}
${new Date().toLocaleDateString('zh-CN')}`;

  res.json({ subject, body });
});

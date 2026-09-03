import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, type RagMentor } from '../data/ragAdvisors';
import { loadLatestMentorMatchArtifact } from '../data/runArtifacts';
import { loadRecommendMemory, studentIdentity, verifiedPaperTitles } from '../data/userMemory';
import { loadUserProfile } from '../data/growthStore';
import { cleanTopics, stripEnumeratedPrefix } from '../data/topicBoilerplate';
import { buildScenarioEmail, EMAIL_SCENARIOS, type EmailScenarioId } from '../data/emailTemplates';
import { agentBase, emailGrowthPatch, probeAgent, runHarnessSkill } from '../harnessClient';
import {
  drainEmailOutbox, getEmailSettings, imapConfigured, probeImap, probeSmtp,
  queueEmail, readInbox, saveEmailSettings, smtpConfigured,
  type EmailAttachmentInput,
} from '../services/mailer';
import { ensureProductivitySchema, getDb } from '../db';

export const emailRouter = Router();

emailRouter.use(authMiddleware);

interface EmailRequestBody {
  advisor_id?: string;
  subject?: string;
  body?: string;
  recipients?: unknown;
  smtp_password?: unknown;
  attachments?: unknown;
  email_scenario?: unknown;
}

const EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig;
const USTC_CLIENT_PASSWORD_PATTERN = /^[A-Za-z0-9]{16}$/;
const MAX_EMAIL_ATTACHMENTS = 5;
const MAX_EMAIL_ATTACHMENT_BYTES = 20 * 1024 * 1024;

function validatedEmailAttachments(value: unknown): { ok: true; items: EmailAttachmentInput[] } | { ok: false; error: string } {
  if (value === undefined || value === null) return { ok: true, items: [] };
  if (!Array.isArray(value)) return { ok: false, error: '附件格式不正确' };
  if (value.length > MAX_EMAIL_ATTACHMENTS) return { ok: false, error: `一次最多添加 ${MAX_EMAIL_ATTACHMENTS} 个附件` };
  const items: EmailAttachmentInput[] = [];
  let totalBytes = 0;
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') return { ok: false, error: '附件格式不正确' };
    const item = raw as Record<string, unknown>;
    const filename = String(item.filename || '').trim().slice(0, 180);
    const content = String(item.contentBase64 || '');
    const dataStart = content.indexOf(',');
    const base64 = dataStart >= 0 ? content.slice(dataStart + 1) : content;
    if (!filename || !base64 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64.replace(/\s+/g, ''))) {
      return { ok: false, error: '附件内容无效，请重新选择文件' };
    }
    totalBytes += Math.floor((base64.replace(/\s+/g, '').length * 3) / 4);
    if (totalBytes > MAX_EMAIL_ATTACHMENT_BYTES) {
      return { ok: false, error: '附件总大小不能超过 20MB' };
    }
    items.push({
      filename,
      contentBase64: base64.replace(/\s+/g, ''),
      contentType: typeof item.contentType === 'string' && item.contentType.trim() ? item.contentType.trim().slice(0, 100) : undefined,
    });
  }
  return { ok: true, items };
}

function isUstcMailHost(value: unknown): boolean {
  return String(value || '').toLowerCase().includes('ustc.edu.cn');
}

function isUstcClientPassword(value: unknown): boolean {
  return USTC_CLIENT_PASSWORD_PATTERN.test(String(value || '').trim());
}

function textList(value: unknown, limit = 8): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    const text = String(item || '').replace(/\s+/g, ' ').trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    result.push(text);
    if (result.length >= limit) break;
  }
  return result;
}

function mentorEmail(candidate: RagMentor): string {
  const sources = [
    candidate.source_metadata?.profile_email,
    ...(String(candidate.source_metadata?.profile_bio || '').match(EMAIL_PATTERN) || []),
    ...(String(candidate.recruitment_status || '').match(EMAIL_PATTERN) || []),
  ];
  for (const source of sources) {
    const address = String(source || '').trim().toLowerCase();
    if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) return address;
  }
  return '';
}

function normalizeRecipients(value: unknown, fallback = ''): string[] {
  const raw = Array.isArray(value) ? value : [value || fallback];
  const addresses = raw
    .flatMap((item) => String(item || '').split(/[;,，；\s]+/))
    .map((item) => item.trim().toLowerCase())
    .filter((item, index, all) => item && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(item) && all.indexOf(item) === index);
  return addresses.slice(0, 20);
}

function articleUnderstanding(title: string, topics: string[], methods: string[]): string {
  const topicText = topics.slice(0, 2).join('与') || '相关科学问题';
  const methodText = methods.slice(0, 2).join('、');
  const normalized = title.toLowerCase();
  if (/deep learning potential|deep potential|potential energy model/.test(normalized)) {
    return `从公开题目和研究方向看，我理解这项工作是把主动学习与深度学习势能模型结合起来，通过不断发现并补充有代表性的训练数据，提高模型对复杂原子/分子体系的可靠性与适用范围。`;
  }
  if (/graph neural|gnn/.test(normalized)) {
    return `从公开题目和研究方向看，我理解这项工作关注用图神经网络表达原子、分子或复杂系统中的结构关系，并把这种结构化表示用于提升${topicText}问题的建模能力。`;
  }
  if (/molecular dynamics|reaction|combustion|chemical/.test(normalized)) {
    return `从公开题目和研究方向看，我理解这项工作尝试将${methodText || '机器学习方法'}用于${topicText}相关的动态过程分析，在保证计算效率的同时帮助研究者理解复杂反应或材料体系的演化规律。`;
  }
  if (/software|toolkit|framework|platform|generator|dispatcher/.test(normalized)) {
    return `从公开题目和研究方向看，我理解这项工作不仅关注理论方法，也重视把${topicText}相关方法沉淀为可复用的软件、工具链或计算平台，从而让后续研究能够更稳定、可扩展地开展。`;
  }
  return `从论文题目及公开资料呈现的信息看，我理解这项工作围绕${topicText}展开，重点是将${methodText || '数据驱动的方法'}用于解决具体研究问题；这也让我对该方向从问题定义、方法设计到实验验证的完整过程产生了兴趣。`;
}

function fillKnownFields(text: string, student: ReturnType<typeof studentIdentity>, papers: string[]): string {
  let out = String(text || '');
  if (student.name) out = out.replace(/\[请填写姓名\]/g, student.name);
  if (student.education) out = out.replace(/\[请填写当前学历\/年级\]/g, student.education);
  if (papers[0]) {
    out = out.replace(/\[请从已核验证据中选择论文\]/g, papers[0]);
  } else {
    out = out.replace(/注意到公开资料中有《\s*\[请从已核验证据中选择论文\]\s*》。?/g, '');
    out = out.replace(/\[请从已核验证据中选择论文\]/g, '');
  }
  if (student.email && !out.toLowerCase().includes(student.email.toLowerCase())) {
    out = `${out.trim()}\n${student.email}`;
  }
  return out.replace(/\n{3,}/g, '\n\n').trim();
}

function localContactDraft(
  candidate: RagMentor,
  student: ReturnType<typeof studentIdentity>,
  papers: string[],
  memory: ReturnType<typeof loadRecommendMemory>,
  profile: ReturnType<typeof loadUserProfile>,
): { subject: string; body: string } {
  const direction = stripEnumeratedPrefix(memory.core[0])
    || cleanTopics(candidate.research_topics, candidate.mentor_name)[0]
    || '相关研究';
  const topics = cleanTopics(candidate.research_topics, candidate.mentor_name);
  const publication = stripEnumeratedPrefix(papers[0] || candidate.publications?.[0] || '');
  const understanding = publication ? articleUnderstanding(publication, topics, candidate.methods || []) : '';
  const profileName = String(profile.nickname || '').trim();
  const profileEducation = [profile.grade, profile.major].map((value) => String(value || '').trim()).filter(Boolean).join(' / ');
  const profileBio = String(profile.bio || '').replace(/\s+/g, ' ').trim();
  const profileSkills = textList(profile.skills);
  const profileInterests = textList(profile.interests);
  const personalInfoPrompt = '【个人信息】（请填写姓名、学校、年级/专业，以及与申请研究相关的学习背景、技能或经历。）';
  const paperPrompt = '【论文与具体想法】（请补充导师的一篇代表性论文，并写下你对其研究问题、方法或结果的理解，以及希望进一步学习的问题。）';
  const identityLine = [
    profileName ? `我是${profileName}` : '',
    profileEducation ? `目前就读于${profileEducation}` : '',
  ].filter(Boolean).join('，');
  const lines = [
    `${candidate.mentor_name}老师您好：`,
    '',
    identityLine ? `${identityLine}。` : personalInfoPrompt,
    profileBio ? `我对自己的介绍是：${profileBio}。` : '',
    profileSkills.length ? `目前我重点积累的能力包括：${profileSkills.join('、')}。` : '',
    '',
    `我近期持续关注您在${candidate.department || '中国科学技术大学'}开展的${topics.slice(0, 4).join('、') || direction}研究。${profileInterests.length ? `结合我对${profileInterests.join('、')}的兴趣，我尤其希望了解这些方向如何转化为具体的研究问题。` : `我希望进一步理解这些方向背后的关键问题、研究方法与实际应用。`}`,
    publication ? `我尤其关注您的代表性论文《${publication}》。${understanding} 这项工作让我认识到，严谨的问题建模、可靠的数据或实验设计，以及方法在真实科研场景中的可复现性同样重要。` : paperPrompt,
    '',
    `如果您目前有适合学生参与的科研、实习或研究生申请机会，我非常希望有机会进入您的课题组/实验室，在您的指导下从基础工作做起，认真学习并承担力所能及的任务。若目前暂无合适名额，也恳请您在方便时指点我应当补充哪些知识与准备。`,
    '',
    '感谢您在百忙之中阅读这封邮件，期待有机会向您进一步请教。',
    '',
    '此致',
    '敬礼',
    '',
    profileName || '【个人信息】',
    student.email,
  ].filter((line, index, all) => line || (index > 0 && all[index - 1] !== '')).join('\n');
  return {
    subject: `咨询${direction}方向的研究机会——${candidate.mentor_name}老师`,
    body: lines.trim(),
  };
}

emailRouter.get('/settings', (req: AuthRequest, res: Response) => {
  res.json(getEmailSettings(req.userId!));
});

emailRouter.put('/settings', (req: AuthRequest, res: Response) => {
  const body = (req.body ?? {}) as Record<string, unknown>;
  const addressFields = ['smtp_user', 'smtp_from', 'imap_user'];
  for (const field of addressFields) {
    const value = String(body[field] || '').trim();
    const address = value.match(/<\s*([^<>\s]+@[^<>\s]+)\s*>/)?.[1] || value;
    if (value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) {
      res.status(400).json({ message: `${field} 不是有效邮箱地址` });
      return;
    }
  }
  const portFields = ['smtp_port', 'imap_port'];
  for (const field of portFields) {
    const port = Number(body[field]);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      res.status(400).json({ message: `${field} 不是有效端口` });
      return;
    }
  }
  const hostFields = ['smtp_host', 'imap_host'];
  for (const field of hostFields) {
    const value = String(body[field] || '').trim();
    if (value && (value.includes('@') || /\s/.test(value))) {
      res.status(400).json({ message: `${field} 应填写服务器地址，例如 mail.ustc.edu.cn，不是邮箱地址` });
      return;
    }
  }
  const smtpPasswordValue = body.smtp_password === undefined ? '' : String(body.smtp_password || '');
  const currentSettings = getEmailSettings(req.userId!);
  const effectiveSmtpHost = String(body.smtp_host ?? currentSettings.smtp_host);
  if (smtpPasswordValue && isUstcMailHost(effectiveSmtpHost) && !isUstcClientPassword(smtpPasswordValue)) {
    res.status(400).json({ message: 'USTC 客户端专用密码应为 16 位字母或数字（不含空格），请去掉空格后重试' });
    return;
  }
  res.json(saveEmailSettings(req.userId!, body));
});

emailRouter.get('/status', async (req: AuthRequest, res: Response) => {
  const smtpPassword = req.get('x-smtp-password') || undefined;
  const imapPassword = req.get('x-imap-password') || smtpPassword;
  const [smtp, imap] = await Promise.all([
    probeSmtp(4000, req.userId!, smtpPassword),
    probeImap(4000, req.userId!, imapPassword),
  ]);
  res.json({ smtp, imap });
});

emailRouter.post('/generate', async (req: AuthRequest, res: Response) => {
  const { advisor_id, email_scenario } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id) {
    res.status(400).json({ message: '请提供 advisor_id' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  if (!candidate) {
    res.status(404).json({ message: '未找到该导师' });
    return;
  }
  const student = studentIdentity(req.userId!);
  const profile = loadUserProfile(req.userId!);
  const papers = verifiedPaperTitles(req.userId!, advisor_id);
  const memory = loadRecommendMemory(req.userId!);
  const requestedScenario = String(email_scenario || 'postgraduate') as EmailScenarioId;
  const scenario = EMAIL_SCENARIOS.some((item) => item.value === requestedScenario)
    ? requestedScenario
    : 'postgraduate';
  const scenarioDraft = buildScenarioEmail(scenario, {
    candidate,
    profile,
    papers,
    memoryCore: memory.core,
  });
  res.json({
    ...scenarioDraft,
    default_recipients: mentorEmail(candidate) ? [mentorEmail(candidate)] : [],
    source: `local:${scenario}`,
  });
  return;

  const local = localContactDraft(candidate, student, papers, memory, profile);
  const matchArtifact = loadLatestMentorMatchArtifact(req.userId!, advisor_id);
  const resumeTraceId = matchArtifact?.trace_id ? String(matchArtifact.trace_id) : '';

  if (agentBase() && await probeAgent(2500)) {
    try {
      const result = await runHarnessSkill({
        userId: req.userId!,
        skillId: 'email_compose',
        message: `生成联系 ${candidate.mentor_name} 的邮件`,
        query: advisor_id,
        timeoutMs: Math.max(60_000, Number(process.env.EMAIL_AGENT_TIMEOUT_MS || 150_000)),
        context: {
          candidate_id: advisor_id,
          resume_trace_id: resumeTraceId || undefined,
          student,
          profile,
          verified_papers: papers,
          recommend_memory: memory,
        },
        patcher: (runId, payload) => emailGrowthPatch(runId, advisor_id, payload),
      });
      const artifact = result?.artifact ?? {};
      if (result?.review_status === 'PASS' && artifact.subject && artifact.body) {
        res.json({
          subject: fillKnownFields(String(artifact.subject), student, papers),
          body: fillKnownFields(String(artifact.body), student, papers),
          default_recipients: mentorEmail(candidate) ? [mentorEmail(candidate)] : [],
          run_id: result.run_id,
          review_status: result.review_status,
          evidence_refs: result.evidence_refs,
          source: 'harness',
        });
        return;
      }
    } catch {
      // 本地草稿使用同一套记忆，不把 Agent 失败伪装成审核通过。
    }
  }

  res.json({ ...local, default_recipients: mentorEmail(candidate) ? [mentorEmail(candidate)] : [], source: 'local' });
});

emailRouter.post('/send', async (req: AuthRequest, res: Response) => {
  const { advisor_id, subject, body, recipients, smtp_password, attachments } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id || !String(subject || '').trim() || !String(body || '').trim()) {
    res.status(400).json({ message: '导师、主题和正文不能为空' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  if (!candidate) { res.status(404).json({ message: '未找到该导师' }); return; }
  const targetRecipients = normalizeRecipients(recipients, mentorEmail(candidate));
  if (!targetRecipients.length) {
    res.status(400).json({ message: '请至少填写一个有效收件人邮箱' });
    return;
  }
  const validatedAttachments = validatedEmailAttachments(attachments);
  if (!validatedAttachments.ok) {
    res.status(400).json({ message: validatedAttachments.error });
    return;
  }
  ensureProductivitySchema(getDb());
  const outboxIds = targetRecipients.map((recipient) => queueEmail({
    userId: req.userId!, recipient,
    subject: String(subject).replace(/[\r\n]+/g, ' ').trim().slice(0, 300),
    body: String(body).trim().slice(0, 30000), kind: `advisor-contact:${advisor_id}`,
    attachments: validatedAttachments.items,
  }));
  const transientPassword = typeof smtp_password === 'string' ? smtp_password : undefined;
  const delivery = await drainEmailOutbox(targetRecipients.length, req.userId!, transientPassword, outboxIds);
  const placeholders = outboxIds.map((id) => getDb().prepare('SELECT id,recipient,subject,kind,status,sent_at,error,created_at FROM email_outbox WHERE id=? AND user_id=?').get(id, req.userId!));
  const rows = placeholders.filter(Boolean) as Array<{ status?: string }>;
  const allSent = rows.length === outboxIds.length && rows.every((row) => row.status === 'sent');
  res.status(allSent ? 200 : 202).json({ item: rows[0], items: rows, smtp_configured: delivery.configured });
});

emailRouter.get('/outbox', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const items = getDb().prepare(
    'SELECT id,recipient,subject,kind,status,scheduled_at,sent_at,error,created_at FROM email_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100',
  ).all(req.userId!);
  res.json({ smtp_configured: smtpConfigured(req.userId!), items });
});

emailRouter.get('/inbox', async (req: AuthRequest, res: Response) => {
  const password = req.get('x-imap-password') || req.get('x-smtp-password') || undefined;
  if (!imapConfigured(req.userId!, password)) { res.json({ imap_configured: false, items: [] }); return; }
  try {
    res.json({ imap_configured: true, items: await readInbox(30, req.userId!, password) });
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? `读取收件箱失败：${error.message}` : '读取收件箱失败' });
  }
});

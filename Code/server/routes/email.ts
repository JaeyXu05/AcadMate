import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { ragStore, type RagMentor } from '../data/ragAdvisors';
import { loadLatestMentorMatchArtifact } from '../data/runArtifacts';
import { loadRecommendMemory, studentIdentity, verifiedPaperTitles } from '../data/userMemory';
import { cleanTopics } from '../data/topicBoilerplate';
import { agentBase, emailGrowthPatch, probeAgent, runHarnessSkill } from '../harnessClient';
import {
  configuredImapUser, drainEmailOutbox, imapConfigured, probeImap, probeSmtp,
  queueEmail, readInbox, smtpConfigured,
} from '../services/mailer';
import { ensureProductivitySchema, getDb } from '../db';

export const emailRouter = Router();

emailRouter.use(authMiddleware);

interface EmailRequestBody {
  advisor_id?: string;
  subject?: string;
  body?: string;
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
  return out.replace(/\n{3,}/g, '\n\n').trim();
}

function localContactDraft(
  candidate: RagMentor,
  student: ReturnType<typeof studentIdentity>,
  papers: string[],
  memory: ReturnType<typeof loadRecommendMemory>,
): { subject: string; body: string } {
  const direction = memory.core[0] || cleanTopics(candidate.research_topics, candidate.mentor_name)[0] || '相关研究';
  const who = student.name
    ? (student.education ? `我是${student.name}，目前为${student.education}。` : `我是${student.name}。`)
    : (student.education ? `我目前为${student.education}。` : '');
  const paper = papers[0] ? `注意到公开资料中有《${papers[0]}》。` : '';
  const lines = [
    `${candidate.mentor_name}老师您好：`,
    '',
    [who, `近期关注到您在${candidate.department || '贵单位'}的「${direction}」方向研究。`, paper].filter(Boolean).join(''),
    '',
    '冒昧联系，希望有机会进一步请教。',
    '',
    '此致',
    '敬礼',
  ];
  return {
    subject: `请教${candidate.mentor_name}老师关于${direction}的研究`,
    body: lines.join('\n'),
  };
}

emailRouter.get('/status', async (_req: AuthRequest, res: Response) => {
  const [smtp, imap] = await Promise.all([probeSmtp(), probeImap()]);
  res.json({ smtp, imap });
});

emailRouter.post('/generate', async (req: AuthRequest, res: Response) => {
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
  const student = studentIdentity(req.userId!);
  const papers = verifiedPaperTitles(req.userId!, advisor_id);
  const memory = loadRecommendMemory(req.userId!);
  const local = localContactDraft(candidate, student, papers, memory);
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

  res.json({ ...local, source: 'local' });
});

emailRouter.post('/send', async (req: AuthRequest, res: Response) => {
  const { advisor_id, subject, body } = (req.body ?? {}) as EmailRequestBody;
  if (!advisor_id || !String(subject || '').trim() || !String(body || '').trim()) {
    res.status(400).json({ message: '导师、主题和正文不能为空' });
    return;
  }
  const candidate = ragStore.getById(advisor_id);
  const recipient = String(candidate?.source_metadata?.profile_email || '').trim();
  if (!candidate) { res.status(404).json({ message: '未找到该导师' }); return; }
  if (!recipient || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(recipient)) {
    res.status(409).json({ message: '该导师没有经官网资料验证的邮箱，不能自动发送' });
    return;
  }
  ensureProductivitySchema(getDb());
  const outboxId = queueEmail({
    userId: req.userId!, recipient,
    subject: String(subject).replace(/[\r\n]+/g, ' ').trim().slice(0, 300),
    body: String(body).trim().slice(0, 30000), kind: `advisor-contact:${advisor_id}`,
  });
  const delivery = await drainEmailOutbox(1);
  const row = getDb().prepare('SELECT id,recipient,subject,kind,status,sent_at,error,created_at FROM email_outbox WHERE id=? AND user_id=?').get(outboxId, req.userId!) as { status?: string } | undefined;
  res.status(row?.status === 'sent' ? 200 : 202).json({ item: row, smtp_configured: delivery.configured });
});

emailRouter.get('/outbox', (req: AuthRequest, res: Response) => {
  ensureProductivitySchema(getDb());
  const items = getDb().prepare(
    'SELECT id,recipient,subject,kind,status,scheduled_at,sent_at,error,created_at FROM email_outbox WHERE user_id=? ORDER BY id DESC LIMIT 100',
  ).all(req.userId!);
  res.json({ smtp_configured: smtpConfigured(), items });
});

emailRouter.get('/inbox', async (req: AuthRequest, res: Response) => {
  const user = getDb().prepare('SELECT email FROM users WHERE id=?').get(req.userId!) as { email: string } | undefined;
  if (!imapConfigured()) { res.json({ imap_configured: false, items: [] }); return; }
  if (!user || user.email.trim().toLowerCase() !== configuredImapUser()) {
    res.status(403).json({ message: '为保护邮箱隐私，只有与 IMAP 配置一致的注册邮箱可以读取收件箱' });
    return;
  }
  try {
    res.json({ imap_configured: true, items: await readInbox(30) });
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? `读取收件箱失败：${error.message}` : '读取收件箱失败' });
  }
});

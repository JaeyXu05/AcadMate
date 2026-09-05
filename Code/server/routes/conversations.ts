import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { getDb } from '../db';
import { agentBase, agentUrl, probeAgent, probeResearchChat } from '../harnessClient';
import { getLlmApiSettings } from '../services/llmSettings';
import {
  RESEARCH_ASSISTANT_INSTRUCTIONS,
  explainResearchStreamError,
  researchAgentOverrides,
  researchAgentTimeoutMs,
} from '../researchRuntime';

export const conversationsRouter = Router();
conversationsRouter.use(authMiddleware);

function jsonValue(value: unknown, fallback: unknown): unknown {
  if (typeof value !== 'string' || !value.trim()) return fallback;
  try { return JSON.parse(value); } catch { return fallback; }
}

function userConversation(userId: number, id: number): any | undefined {
  return getDb().prepare('SELECT * FROM conversations WHERE id=? AND user_id=?').get(id, userId) as any;
}

function userProject(userId: number, id: number): any | undefined {
  return getDb().prepare('SELECT * FROM research_projects WHERE id=? AND user_id=?').get(id, userId) as any;
}

function conversationRead(userId: number, id: number): any | undefined {
  const conversation = userConversation(userId, id);
  if (!conversation) return undefined;
  const db = getDb();
  const goals = db.prepare(
    'SELECT id, conversation_id, version, title, description, status, source, created_at FROM conversation_goals WHERE conversation_id=? AND user_id=? ORDER BY version DESC',
  ).all(id, userId) as any[];
  const messages = db.prepare(
    'SELECT id, role, content, metadata_json, created_at FROM conversation_messages WHERE conversation_id=? AND user_id=? ORDER BY id',
  ).all(id, userId) as any[];
  const activeGoal = goals.find((item) => item.id === conversation.active_goal_id) ?? goals[0] ?? null;
  return {
    ...conversation,
    metadata: jsonValue(conversation.metadata_json, {}),
    active_goal: activeGoal,
    goals: goals.map(({ metadata_json: _ignored, ...item }) => item),
    messages: messages.map((item) => ({
      ...item,
      metadata: jsonValue(item.metadata_json, {}),
    })),
  };
}

function parseId(value: string): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

conversationsRouter.get('/', (req: AuthRequest, res: Response) => {
  const surface = typeof req.query.surface === 'string' ? req.query.surface : '';
  const projectId = typeof req.query.project_id === 'string' ? parseId(req.query.project_id) : null;
  const where = ['user_id=?'];
  const params: Array<number | string> = [req.userId!];
  if (surface === 'search' || surface === 'research') { where.push('surface=?'); params.push(surface); }
  if (projectId) { where.push('project_id=?'); params.push(projectId); }
  const rows = getDb().prepare(
    `SELECT id, project_id, surface, title, status, active_goal_id, agent_thread_id, created_at, updated_at
     FROM conversations WHERE ${where.join(' AND ')} ORDER BY updated_at DESC, id DESC LIMIT 100`,
  ).all(...params) as any[];
  res.json(rows);
});

conversationsRouter.post('/', (req: AuthRequest, res: Response) => {
  const body = req.body ?? {};
  const surface = body.surface === 'search' ? 'search' : 'research';
  const title = String(body.title || '新对话').trim().slice(0, 200) || '新对话';
  const projectId = body.project_id == null ? null : parseId(String(body.project_id));
  if (body.project_id != null && (!projectId || !userProject(req.userId!, projectId))) {
    res.status(400).json({ message: '科研项目不存在' });
    return;
  }
  const result = getDb().prepare(
    `INSERT INTO conversations (user_id, project_id, surface, title)
     VALUES (?, ?, ?, ?)`,
  ).run(req.userId!, projectId, surface, title);
  res.status(201).json(conversationRead(req.userId!, Number(result.lastInsertRowid)));
});

conversationsRouter.get('/:id', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  const item = id ? conversationRead(req.userId!, id) : undefined;
  if (!item) { res.status(404).json({ message: '会话不存在' }); return; }
  res.json(item);
});

conversationsRouter.patch('/:id', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  if (!id || !userConversation(req.userId!, id)) { res.status(404).json({ message: '会话不存在' }); return; }
  const body = req.body ?? {};
  const updates: string[] = [];
  const params: Array<number | string | null> = [];
  if (body.title !== undefined) { updates.push('title=?'); params.push(String(body.title || '新对话').trim().slice(0, 200) || '新对话'); }
  if (body.status === 'active' || body.status === 'archived') { updates.push('status=?'); params.push(body.status); }
  if (body.project_id !== undefined) {
    const projectId = body.project_id == null ? null : parseId(String(body.project_id));
    if (projectId !== null && !userProject(req.userId!, projectId)) { res.status(400).json({ message: '科研项目不存在' }); return; }
    updates.push('project_id=?'); params.push(projectId);
  }
  if (!updates.length) { res.json(conversationRead(req.userId!, id)); return; }
  updates.push("updated_at=datetime('now','localtime')");
  getDb().prepare(`UPDATE conversations SET ${updates.join(', ')} WHERE id=? AND user_id=?`).run(...params, id, req.userId!);
  res.json(conversationRead(req.userId!, id));
});

conversationsRouter.post('/:id/goals', (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  if (!id || !userConversation(req.userId!, id)) { res.status(404).json({ message: '会话不存在' }); return; }
  const title = String(req.body?.title || req.body?.description || '').trim().slice(0, 500);
  if (!title) { res.status(400).json({ message: '目标内容不能为空' }); return; }
  const description = String(req.body?.description || '').trim().slice(0, 2000);
  const source = req.body?.source === 'suggestion' ? 'suggestion' : 'user';
  const db = getDb();
  const last = db.prepare('SELECT MAX(version) AS version FROM conversation_goals WHERE conversation_id=? AND user_id=?').get(id, req.userId!) as { version?: number };
  const version = Number(last?.version || 0) + 1;
  const transaction = db.transaction(() => {
    db.prepare("UPDATE conversation_goals SET status='superseded' WHERE conversation_id=? AND user_id=? AND status='active'").run(id, req.userId!);
    const result = db.prepare(
      `INSERT INTO conversation_goals (conversation_id, user_id, version, title, description, source)
       VALUES (?, ?, ?, ?, ?, ?)`,
    ).run(id, req.userId!, version, title, description, source);
    db.prepare("UPDATE conversations SET active_goal_id=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(Number(result.lastInsertRowid), id, req.userId!);
    return Number(result.lastInsertRowid);
  });
  const goalId = transaction();
  res.status(201).json(db.prepare('SELECT id, conversation_id, version, title, description, status, source, created_at FROM conversation_goals WHERE id=?').get(goalId));
});

conversationsRouter.patch('/goals/:goalId', (req: AuthRequest, res: Response) => {
  const goalId = parseId(req.params.goalId);
  const goal = goalId ? getDb().prepare('SELECT * FROM conversation_goals WHERE id=? AND user_id=?').get(goalId, req.userId!) as any : undefined;
  if (!goal) { res.status(404).json({ message: '会话目标不存在' }); return; }
  const status = ['active', 'paused', 'completed', 'superseded'].includes(String(req.body?.status)) ? String(req.body.status) : goal.status;
  getDb().prepare('UPDATE conversation_goals SET status=? WHERE id=? AND user_id=?').run(status, goalId, req.userId!);
  if (status === 'active') {
    getDb().prepare("UPDATE conversations SET active_goal_id=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(goalId, goal.conversation_id, req.userId!);
  }
  res.json(getDb().prepare('SELECT id, conversation_id, version, title, description, status, source, created_at FROM conversation_goals WHERE id=?').get(goalId));
});

function persistAssistantMessage(
  conversationId: number,
  userId: number,
  content: string,
  metadata: Record<string, unknown>,
): void {
  const text = content.trim();
  if (!text) return;
  getDb().prepare(
    'INSERT INTO conversation_messages (conversation_id, user_id, role, content, metadata_json) VALUES (?, ?, ?, ?, ?)',
  ).run(conversationId, userId, 'assistant', text, JSON.stringify(metadata));
}

function flushStream(res: Response): void {
  const flushable = res as Response & { flush?: () => void };
  if (typeof flushable.flush === 'function') flushable.flush();
}

conversationsRouter.post('/:id/messages/stream', async (req: AuthRequest, res: Response) => {
  const id = parseId(req.params.id);
  const conversation = id ? userConversation(req.userId!, id) : undefined;
  const message = String(req.body?.message || '').trim();
  if (!conversation) { res.status(404).json({ message: '会话不存在' }); return; }
  if (!message) { res.status(400).json({ message: '消息不能为空' }); return; }
  const db = getDb();
  db.prepare('INSERT INTO conversation_messages (conversation_id, user_id, role, content) VALUES (?, ?, ?, ?)').run(id, req.userId!, 'user', message);
  db.prepare("UPDATE conversations SET updated_at=datetime('now','localtime') WHERE id=? AND user_id=?").run(id, req.userId!);
  const activePaperId = parseId(req.body?.active_paper_id);
  if (activePaperId) {
    const metadata = jsonValue(conversation.metadata_json, {}) as Record<string, unknown>;
    metadata.active_paper_id = activePaperId;
    if (typeof req.body?.active_paper_title === 'string' && req.body.active_paper_title.trim()) {
      metadata.active_paper_title = req.body.active_paper_title.trim().slice(0, 500);
    }
    db.prepare("UPDATE conversations SET metadata_json=?, updated_at=datetime('now','localtime') WHERE id=? AND user_id=?")
      .run(JSON.stringify(metadata), id, req.userId!);
  }
  const base = agentBase();
  if (!base) {
    persistAssistantMessage(id!, req.userId!, 'PAPERCLAW Agent 未配置，无法生成科研回复。请检查 MENTOR_AGENT_BASE_URL 后重试。', {
      source: 'paperclaw',
      error: true,
    });
    res.status(503).json({ message: 'PAPERCLAW Agent 未配置' });
    return;
  }
  if (!await probeAgent(1500)) {
    const message = 'PAPERCLAW Agent 当前未就绪（数据库或上游依赖不可用），请稍后重试。';
    persistAssistantMessage(id!, req.userId!, message, { source: 'paperclaw', error: true });
    res.status(503).json({ message });
    return;
  }
  if (conversation.surface === 'research') {
    const chatReady = await probeResearchChat(req.userId!, 10_000);
    if (!chatReady.ready) {
      const failure = explainResearchStreamError(
        new Error(chatReady.error || 'chat_gateway_unreachable'),
        researchAgentTimeoutMs(),
      ).message;
      persistAssistantMessage(id!, req.userId!, `这次处理没有完成：${failure}`, {
        source: 'paperclaw',
        error: true,
        phase: 'chat_preflight',
      });
      res.status(503).json({ message: failure });
      return;
    }
  }

  const controller = new AbortController();
  const timeoutMs = researchAgentTimeoutMs();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  res.on('close', () => controller.abort());
  let settled = false;
  let assistantText = '';
  try {
    const activeGoal = conversation.active_goal_id
      ? db.prepare('SELECT id, version, title, description, status FROM conversation_goals WHERE id=? AND user_id=?').get(conversation.active_goal_id, req.userId!)
      : null;
    const enabledSkills = db.prepare(
      'SELECT name, description, prompt_template, permissions FROM custom_skills WHERE user_id=? AND status=\'enabled\' ORDER BY updated_at DESC LIMIT 6',
    ).all(req.userId!) as Array<{ name: string; description: string; prompt_template: string; permissions: string }>;
    const extraInstructions = [
      conversation.surface === 'research' ? RESEARCH_ASSISTANT_INSTRUCTIONS : '',
      activeGoal ? `当前会话目标：${String((activeGoal as any).title || '')}${(activeGoal as any).description ? `\n目标说明：${String((activeGoal as any).description)}` : ''}` : '',
      enabledSkills.length ? `用户已启用以下声明式 Skill。仅在当前问题相关且权限允许时参考，不要声称已执行未授权工具：\n${enabledSkills.map((skill) => `- ${skill.name}：${skill.description || '无说明'}\n  指令：${String(skill.prompt_template || '').slice(0, 1800)}`).join('\n')}` : '',
    ].filter(Boolean).join('\n\n').slice(0, 10000);
    const userLlm = getLlmApiSettings(req.userId!, true);
    const userModelOverrides = userLlm.enabled && userLlm.baseUrl && userLlm.model && userLlm.apiKey
      ? { model: userLlm.model, api_key: userLlm.apiKey, base_url: userLlm.baseUrl }
      : {};
    const upstream = await fetch(agentUrl('/api/agent/messages/stream'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: conversation.agent_thread_id || undefined,
        message,
        active_paper_id: req.body?.active_paper_id || undefined,
        ...researchAgentOverrides(conversation.surface),
        ...userModelOverrides,
        metadata: {
          surface: conversation.surface,
          owner_id: String(req.userId!),
          conversation_id: String(id),
          project_id: conversation.project_id ? String(conversation.project_id) : undefined,
          active_goal: activeGoal,
          extra_instructions: extraInstructions || undefined,
        },
      }),
      signal: controller.signal,
    });
    if (!upstream.ok || !upstream.body) {
      const detail = (await upstream.text().catch(() => '')).slice(0, 500);
      const rawFailure = detail || 'PAPERCLAW Agent 调用失败';
      const failure = conversation.surface === 'research'
        ? explainResearchStreamError(new Error(rawFailure), timeoutMs).message
        : rawFailure;
      persistAssistantMessage(id!, req.userId!, `这次处理没有完成：${failure}`, { source: 'paperclaw', error: true });
      res.status(upstream.status || 502).json({ message: failure });
      return;
    }
    res.status(200);
    res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();
    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let terminalType = '';
    let terminalError = '';
    const consume = (line: string) => {
      if (!line.trim()) return;
      let outputLine = line;
      try {
        const event = JSON.parse(line) as { type?: string; thread_id?: number; message?: string; error?: string };
        if (event.thread_id && !conversation.agent_thread_id) {
          db.prepare('UPDATE conversations SET agent_thread_id=?, updated_at=datetime(\'now\',\'localtime\') WHERE id=? AND user_id=?').run(event.thread_id, id, req.userId!);
          conversation.agent_thread_id = event.thread_id;
        }
        if (event.type === 'agent_chunk' && event.message) assistantText += event.message;
        if (event.type === 'run_completed') {
          terminalType = event.type;
          if (event.message) assistantText = event.message;
        }
        if (event.type === 'run_failed' || event.type === 'run_cancelled' || event.type === 'run_waiting_for_user') {
          terminalType = event.type;
          terminalError = String(event.error || event.message || '');
          if (event.type === 'run_failed' && conversation.surface === 'research') {
            terminalError = explainResearchStreamError(new Error(terminalError || 'PAPERCLAW Agent 调用失败'), timeoutMs).message;
            event.error = terminalError;
            outputLine = JSON.stringify(event);
          }
        }
      } catch { /* 保持原始事件透传 */ }
      res.write(`${outputLine}\n`);
      flushStream(res);
    };
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) consume(line);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
    const fallback = '科研助手没有返回文字内容。请再试一次，或改用右侧「论文检索」。';
    let saved = assistantText.trim();
    if (!saved && terminalType === 'run_failed') {
      const failure = conversation.surface === 'research'
        ? explainResearchStreamError(new Error(terminalError || 'PAPERCLAW Agent 调用失败'), timeoutMs).message
        : (terminalError || 'PAPERCLAW Agent 调用失败');
      saved = `这次处理没有完成：${failure}`;
    }
    if (!saved && terminalType === 'run_cancelled') saved = '这次科研对话已被取消。';
    if (!saved && terminalType === 'run_waiting_for_user') saved = '需要你确认后才能继续。请在对话里明确选择论文，或使用右侧论文检索。';
    if (!saved) saved = fallback;
    persistAssistantMessage(id!, req.userId!, saved, { source: 'paperclaw', terminal: terminalType || 'run_completed' });
    settled = true;
    res.end();
  } catch (error) {
    const { timedOut, message: failure } = explainResearchStreamError(error, timeoutMs);
    if (!settled) {
      const partial = assistantText.trim();
      persistAssistantMessage(
        id!,
        req.userId!,
        partial ? `${partial}\n\n（${failure}）` : `这次处理没有完成：${failure}`,
        { source: 'paperclaw', error: true, partial: Boolean(partial) },
      );
    }
    if (!res.headersSent) { res.status(timedOut ? 504 : 502).json({ message: failure }); return; }
    if (!settled) {
      res.write(`${JSON.stringify({ type: 'run_failed', status: 'failed', error: failure, message: assistantText.trim() || undefined })}\n`);
      res.end();
    }
  } finally {
    clearTimeout(timer);
  }
});

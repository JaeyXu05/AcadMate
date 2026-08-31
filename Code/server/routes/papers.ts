import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { getDb } from '../db';
import { agentBase, agentTimeoutMs, agentUrl, probeAgent } from '../harnessClient';

export const papersRouter = Router();
papersRouter.use(authMiddleware);

function asId(value: unknown): number | null {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : null;
}

async function readJson(response: globalThis.Response): Promise<any> {
  return response.json().catch(() => ({}));
}

papersRouter.get('/search', async (req: AuthRequest, res: Response) => {
  const query = typeof req.query.query === 'string' ? req.query.query.trim() : '';
  const source = typeof req.query.source === 'string' ? req.query.source : 'openalex';
  const mode = typeof req.query.mode === 'string' ? req.query.mode : 'keyword';
  const limit = Math.min(Math.max(Number(req.query.limit) || 8, 1), 20);
  if (!query) { res.status(400).json({ message: '请输入论文检索词' }); return; }
  if (!agentBase()) { res.status(503).json({ message: 'PAPERCLAW Agent 未配置' }); return; }
  if (!await probeAgent(1500)) { res.status(503).json({ message: 'PAPERCLAW Agent 当前未就绪（数据库或上游依赖不可用）' }); return; }
  const params = new URLSearchParams({ query, source, mode, limit: String(limit) });
  try {
    const upstream = await fetch(agentUrl(`/api/papers/search?${params.toString()}`), {
      signal: AbortSignal.timeout(Math.min(agentTimeoutMs(), 45_000)),
    });
    const payload: any = await readJson(upstream);
    if (!upstream.ok) {
      res.status(upstream.status).json({ message: payload?.detail || payload?.message || '论文检索失败' });
      return;
    }
    const sessionId = asId(payload?.search_session_id);
    if (sessionId) {
      getDb().prepare(
        `INSERT OR IGNORE INTO paper_search_sessions (user_id, agent_session_id, query, source)
         VALUES (?, ?, ?, ?)`,
      ).run(req.userId!, sessionId, query, source);
    }
    res.json(payload);
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? error.message : '论文检索服务不可用' });
  }
});

papersRouter.post('/search/:searchSessionId/confirm', async (req: AuthRequest, res: Response) => {
  const searchSessionId = asId(req.params.searchSessionId);
  const candidateId = asId(req.body?.candidate_id ?? req.body?.candidateId);
  if (!searchSessionId || !candidateId) { res.status(400).json({ message: 'search_session_id 和 candidate_id 必须为正整数' }); return; }
  const owned = getDb().prepare(
    'SELECT 1 FROM paper_search_sessions WHERE user_id=? AND agent_session_id=?',
  ).get(req.userId!, searchSessionId);
  if (!owned) { res.status(404).json({ message: '论文检索会话不存在或不属于当前用户' }); return; }
  if (!agentBase()) { res.status(503).json({ message: 'PAPERCLAW Agent 未配置' }); return; }
  if (!await probeAgent(1500)) { res.status(503).json({ message: 'PAPERCLAW Agent 当前未就绪（数据库或上游依赖不可用）' }); return; }
  try {
    const upstream = await fetch(
      agentUrl(`/api/papers/search/${searchSessionId}/confirm?candidate_id=${candidateId}`),
      { method: 'POST', signal: AbortSignal.timeout(Math.min(agentTimeoutMs(), 45_000)) },
    );
    const payload: any = await readJson(upstream);
    if (!upstream.ok) {
      res.status(upstream.status).json({ message: payload?.detail || payload?.message || '论文选择失败' });
      return;
    }
    res.json(payload);
  } catch (error) {
    res.status(502).json({ message: error instanceof Error ? error.message : '论文选择服务不可用' });
  }
});

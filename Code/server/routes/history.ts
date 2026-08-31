import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const historyRouter = Router();

historyRouter.use(authMiddleware);

interface SearchRow {
  id: number;
  query: string;
  results_count: number;
  created_at: string;
  run_id?: string | null;
  trace_id?: string | null;
}

interface ChatFirstRow {
  id: number;
  session_id: string;
  content: string;
  created_at: string;
}

interface HistoryItem {
  id: string;    // "search_123" or "chat_456"
  type: 'search' | 'chat';
  content: Record<string, unknown>;
  created_at: string;
  _ts: string;
}

/** GET /api/history?page=1&pageSize=20 — 获取历史记录（分页，搜索+对话混合按时间倒序） */
historyRouter.get('/', (req: AuthRequest, res: Response) => {
  const page = Math.max(1, parseInt(req.query.page as string, 10) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(req.query.pageSize as string, 10) || 20));
  const offset = (page - 1) * pageSize;
  // 每表一批加载的行数上限。内存按批受控，不一次性拉全表。
  const WINDOW = pageSize * 2 + 16;

  const db = getDb();
  const userId = req.userId!;

  // ---- 去重线索：用户名下所有 search query（只取一列，很小） ----
  const searchQueryRows = db
    .prepare('SELECT DISTINCT query FROM search_history WHERE user_id = ?')
    .all(userId) as Pick<SearchRow, 'query'>[];
  const searchQuerySet = new Set(searchQueryRows.map((r) => r.query.trim()));

  // ---- 去重后的精确总数（只做轻量统计，不拉全量行） ----
  const searchTotal =
    (db.prepare('SELECT COUNT(*) AS n FROM search_history WHERE user_id = ?').get(userId) as { n: number }).n;
  const chatFirstTotal =
    (db.prepare(
      `SELECT COUNT(*) AS n FROM chat_history ch
       INNER JOIN (
         SELECT session_id, MIN(created_at) as min_ts FROM chat_history
         WHERE user_id = ? AND role = 'user' GROUP BY session_id
       ) first ON ch.session_id = first.session_id AND ch.created_at = first.min_ts AND ch.role = 'user'
       WHERE ch.user_id = ?`
    ).get(userId, userId) as { n: number }).n;
  // 聊天首条中与某条 search query 重复的行数（同一次检索操作写入两条）——按去重后不展示的行数扣减。
  // 用 GROUP BY 统计每个内容出现几次，凡是命中 search 查询的内容，其全部行都算重复（每轮检索
  // 都会写一条等内容的 chat 行），避免按 distinct 去重时对"同一查询搜多次"的场景少扣。
  const chatDupTotal = (() => {
    const grouped = db
      .prepare(
        `SELECT ch.content, COUNT(*) AS n FROM chat_history ch
         INNER JOIN (
           SELECT session_id, MIN(created_at) as min_ts FROM chat_history
           WHERE user_id = ? AND role = 'user' GROUP BY session_id
         ) first ON ch.session_id = first.session_id AND ch.created_at = first.min_ts AND ch.role = 'user'
         WHERE ch.user_id = ?
         GROUP BY ch.content`
      )
      .all(userId, userId) as { content: string; n: number }[];
    return grouped
      .filter((r) => searchQuerySet.has(r.content.trim()))
      .reduce((acc, r) => acc + r.n, 0);
  })();
  const total = searchTotal + Math.max(0, chatFirstTotal - chatDupTotal);

  // ---- 每 session 第一条 user 消息的原始流（跨会话各取最早一轮），用于分页 ----
  const chatFirstSql = `
    SELECT ch.id, ch.session_id, ch.content, ch.created_at
    FROM chat_history ch
    INNER JOIN (
      SELECT session_id, MIN(created_at) as min_ts
      FROM chat_history
      WHERE user_id = ? AND role = 'user'
      GROUP BY session_id
    ) first ON ch.session_id = first.session_id AND ch.created_at = first.min_ts AND ch.role = 'user'
    WHERE ch.user_id = ?
  `;

  const makeSearchItem = (r: SearchRow): HistoryItem => ({
    id: `search_${r.id}`,
    type: 'search',
    content: {
      query: r.query,
      resultsCount: r.results_count,
      runId: r.run_id || undefined,
      traceId: r.trace_id || undefined,
    },
    created_at: r.created_at,
    _ts: r.created_at,
  });
  const makeChatItem = (r: ChatFirstRow): HistoryItem => ({
    id: `chat_${r.id}`,
    type: 'chat',
    content: { sessionId: r.session_id, firstMessage: r.content },
    created_at: r.created_at,
    _ts: r.created_at,
  });

  // 各表按 created_at DESC 分页取原流行（内存受 WINDOW 控制，不一次性拉全表）
  function fetchSearch(off: number): SearchRow[] {
    return db
      .prepare(
        `SELECT id, query, results_count, created_at, run_id, trace_id
         FROM search_history WHERE user_id = ?
         ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`
      )
      .all(userId, WINDOW, off) as SearchRow[];
  }
  function fetchChat(off: number): ChatFirstRow[] {
    return db
      .prepare(`${chatFirstSql} ORDER BY ch.created_at DESC, ch.id DESC LIMIT ? OFFSET ?`)
      .all(userId, userId, WINDOW, off) as ChatFirstRow[];
  }

  // 两条降序流双路归并；聊天侧对重复 search 的行"跳过但不影响游标"（游标按原始行数推进）。
  const merged: HistoryItem[] = [];
  let sc = 0, cc = 0, sDone = false, cDone = false;
  let sItems: SearchRow[] = [], cItems: ChatFirstRow[] = [];
  while (merged.length < offset + pageSize) {
    if (!sDone && sItems.length === 0) {
      sItems = fetchSearch(sc);
      sc += sItems.length;
      if (sItems.length < WINDOW) sDone = true;
    }
    if (!cDone && cItems.length === 0) {
      const raw = fetchChat(cc);
      cc += raw.length; // 游标按原始行数推进（去重不改变 OFFSET）
      cItems = raw;
      if (raw.length < WINDOW) cDone = true;
    }
    // 两路都已取尽（缓冲为空且源耗尽）→ 全部历史已遍历，结束
    if (sDone && sItems.length === 0 && cDone && cItems.length === 0) break;

    // 取两路当前时间更晚者
    let pick: HistoryItem | null = null;
    while (!pick && (sItems.length > 0 || cItems.length > 0)) {
      if (sItems.length === 0) {
        const c = cItems.shift()!;
        if (!searchQuerySet.has(c.content.trim())) pick = makeChatItem(c);
      } else if (cItems.length === 0) {
        pick = makeSearchItem(sItems.shift()!);
      } else if (sItems[0].created_at >= cItems[0].created_at) {
        pick = makeSearchItem(sItems.shift()!);
      } else {
        const c = cItems.shift()!;
        if (!searchQuerySet.has(c.content.trim())) pick = makeChatItem(c);
      }
    }
    if (pick) merged.push(pick);
  }

  const paged = merged.slice(offset, offset + pageSize);

  res.json({
    items: paged.map(({ _ts, ...rest }) => rest),
    total,
    page,
    pageSize,
    hasMore: total > offset + paged.length,
  });
});

/** POST /api/history/search — 记录一次检索（纯 DB 写入，无队友依赖） */
historyRouter.post('/search', (req: AuthRequest, res: Response) => {
  const query = typeof req.body?.query === 'string' ? req.body.query.trim() : '';
  const resultsCount = Number.isFinite(req.body?.results_count) ? Number(req.body.results_count) : 0;
  if (!query) {
    res.status(400).json({ message: 'query 不能为空' });
    return;
  }
  const runId = typeof req.body?.run_id === 'string' ? req.body.run_id : null;
  const traceId = typeof req.body?.trace_id === 'string' ? req.body.trace_id : null;
  const db = getDb();
  const result = db
    .prepare('INSERT INTO search_history (user_id, query, results_count, run_id, trace_id) VALUES (?, ?, ?, ?, ?)')
    .run(req.userId!, query, resultsCount, runId, traceId);
  res.json({ id: result.lastInsertRowid });
});

/** POST /api/history/chat — 记录一条对话消息（纯 DB 写入，无队友依赖） */
historyRouter.post('/chat', (req: AuthRequest, res: Response) => {
  const sessionId = typeof req.body?.session_id === 'string' ? req.body.session_id : '';
  const role = req.body?.role === 'user' ? 'user' : 'agent';
  const content = typeof req.body?.content === 'string' ? req.body.content : '';
  if (!sessionId || !content) {
    res.status(400).json({ message: 'session_id 与 content 不能为空' });
    return;
  }
  const db = getDb();
  const result = db
    .prepare('INSERT INTO chat_history (user_id, session_id, role, content) VALUES (?, ?, ?, ?)')
    .run(req.userId!, sessionId, role, content);
  res.json({ id: result.lastInsertRowid });
});

/** DELETE /api/history — 清空当前用户全部历史 */
historyRouter.delete('/', (req: AuthRequest, res: Response) => {
  const db = getDb();
  const userId = req.userId!;

  const r1 = db.prepare('DELETE FROM search_history WHERE user_id = ?').run(userId);
  const r2 = db.prepare('DELETE FROM chat_history WHERE user_id = ?').run(userId);

  const total = r1.changes + r2.changes;

  res.json({ message: `已清空 ${total} 条历史记录`, deleted: total });
});

/** DELETE /api/history/:encodedId — 删除单条（id 格式: "search_123" 或 "chat_456"） */
historyRouter.delete('/:encodedId', (req: AuthRequest, res: Response) => {
  const encodedId = req.params.encodedId;
  const match = encodedId.match(/^(search|chat)_(\d+)$/);

  if (!match) {
    res.status(400).json({ message: '无效的历史记录 ID 格式，应为 search_<id> 或 chat_<id>' });
    return;
  }

  const type = match[1];
  const id = parseInt(match[2], 10);
  const table = type === 'search' ? 'search_history' : 'chat_history';

  const db = getDb();
  const result = db
    .prepare(`DELETE FROM ${table} WHERE id = ? AND user_id = ?`)
    .run(id, req.userId!);

  if (result.changes === 0) {
    res.status(404).json({ message: '未找到该记录' });
    return;
  }

  res.json({ message: '已删除' });
});
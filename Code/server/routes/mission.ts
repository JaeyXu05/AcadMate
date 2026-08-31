import { Router, Response } from 'express';
import { getDb } from '../db';
import { authMiddleware, AuthRequest } from '../middleware/auth';

export const missionRouter = Router();

missionRouter.use(authMiddleware);

/** 安全解析 SQLite 中的 JSON 字符串（数组/对象），失败给兜底值 */
function safeParse<T>(val: string | null | undefined, fallback: T): T {
  if (!val) return fallback;
  try {
    const parsed = JSON.parse(val);
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

interface MissionRow {
  id: number;
  trace_id: string;
  query: string;
  status: string;
  goal: string;
  advisor_ids: string;
  source: string;
  created_at: string;
  updated_at: string;
}

interface MissionEventRow {
  id: number;
  mission_id: number;
  seq: number;
  event_type: string;
  stage: string;
  sender: string;
  receiver: string;
  payload: string;
  evidence_refs: string;
  state_version: number | null;
  created_at: string;
}

/** 把一行 mission_events 还原成前端 RuntimeEvent（与 agent.ts 的 emitEvent 同形） */
function rowToEvent(r: MissionEventRow) {
  return {
    event_type: r.event_type,
    stage: r.stage || undefined,
    sender: r.sender || undefined,
    receiver: r.receiver || undefined,
    payload: safeParse<Record<string, unknown>>(r.payload, {}),
    evidence_refs: safeParse<string[]>(r.evidence_refs, []),
    state_version: r.state_version ?? undefined,
    seq: r.seq,
    timestamp: r.created_at,
  };
}

function rowToMission(r: MissionRow) {
  return {
    id: r.id,
    trace_id: r.trace_id,
    query: r.query,
    status: r.status,
    goal: r.goal,
    advisor_ids: safeParse<string[]>(r.advisor_ids, []),
    source: r.source,
    created_at: r.created_at,
    updated_at: r.updated_at,
  };
}

/**
 * GET /api/mission — 列出当前用户的检索 Mission（按时间倒序，分页）。
 * 用于历史页 / Workspace「回放此次检索」入口。
 */
missionRouter.get('/', (req: AuthRequest, res: Response) => {
  const page = Math.max(1, parseInt(req.query.page as string, 10) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(req.query.pageSize as string, 10) || 20));
  const offset = (page - 1) * pageSize;
  const userId = req.userId!;

  const db = getDb();
  const total = (db
    .prepare('SELECT COUNT(*) AS n FROM missions WHERE user_id = ?')
    .get(userId) as { n: number }).n;

  const rows = db
    .prepare(
      `SELECT id, trace_id, query, status, goal, advisor_ids, source, created_at, updated_at
       FROM missions WHERE user_id = ?
       ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?`,
    )
    .all(userId, pageSize, offset) as MissionRow[];

  res.json({
    items: rows.map(rowToMission),
    total,
    page,
    pageSize,
    hasMore: total > offset + rows.length,
  });
});

/**
 * GET /api/mission/:id — 单个 Mission 元信息。
 */
missionRouter.get('/:id', (req: AuthRequest, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    res.status(400).json({ message: '无效的 mission id' });
    return;
  }
  const db = getDb();
  const row = db
    .prepare(
      `SELECT id, trace_id, query, status, goal, advisor_ids, source, created_at, updated_at
       FROM missions WHERE id = ? AND user_id = ?`,
    )
    .get(id, req.userId!) as MissionRow | undefined;
  if (!row) {
    res.status(404).json({ message: '未找到该检索任务' });
    return;
  }
  res.json(rowToMission(row));
});

/**
 * GET /api/mission/:id/replay — 回放某次检索的完整事件序列（按 seq 升序）。
 * 校验归属（user_id），返回 { mission, events } 供前端 RuntimeTimeline 复用渲染。
 */
missionRouter.get('/:id/replay', (req: AuthRequest, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    res.status(400).json({ message: '无效的 mission id' });
    return;
  }
  const db = getDb();
  const userId = req.userId!;

  const mission = db
    .prepare(
      `SELECT id, trace_id, query, status, goal, advisor_ids, source, created_at, updated_at
       FROM missions WHERE id = ? AND user_id = ?`,
    )
    .get(id, userId) as MissionRow | undefined;

  if (!mission) {
    res.status(404).json({ message: '未找到该检索任务' });
    return;
  }

  const events = db
    .prepare(
      `SELECT id, mission_id, seq, event_type, stage, sender, receiver, payload, evidence_refs, state_version, created_at
       FROM mission_events WHERE mission_id = ? ORDER BY seq ASC, id ASC`,
    )
    .all(id) as MissionEventRow[];

  res.json({
    mission: rowToMission(mission),
    events: events.map(rowToEvent),
  });
});

/**
 * DELETE /api/mission/:id — 删除单个 Mission 及其事件（级联）。
 */
missionRouter.delete('/:id', (req: AuthRequest, res: Response) => {
  const id = parseInt(req.params.id, 10);
  if (!Number.isFinite(id)) {
    res.status(400).json({ message: '无效的 mission id' });
    return;
  }
  const db = getDb();
  // 先删事件（missions 表 ON DELETE CASCADE 会自动删，但显式删更稳妥/兼容未开 FK 时）
  db.prepare('DELETE FROM mission_events WHERE mission_id = ?').run(id);
  const r = db.prepare('DELETE FROM missions WHERE id = ? AND user_id = ?').run(id, req.userId!);
  if (r.changes === 0) {
    res.status(404).json({ message: '未找到该检索任务' });
    return;
  }
  res.json({ message: '已删除', deleted: r.changes });
});

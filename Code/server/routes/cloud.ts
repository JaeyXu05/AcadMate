import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { ragData } from '../data/ragAdvisors';
import { assessRagSync, buildCloudEdges, normalizeCloudNodes } from './cloudData';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const cloudRouter = Router();

cloudRouter.use(authMiddleware);

/**
 * 3D 云图数据源：由 cloud3d/build_cloud.py 从 RAG 库生成的银河盘数据。
 * - 节点字段完全来自 cloud_data.json（导师数随 RAG 版本变化，含 x/y/z 坐标、领域、亮度、大小、论文等）
 * - edges 边数据 cloud_data.json 不含（只有同域星座连线），这里按「同领域最近邻」动态生成，
 *   形成 3D 星图中的关系连线（同域=same-field）。
 */

// ---- 数据加载（启动时读取一次，缓存）----
let CLOUD_CACHE: {
  nodes: ReturnType<typeof normalizeCloudNodes>['nodes'];
  meta: Record<string, any>;
  diagnostics: Pick<ReturnType<typeof normalizeCloudNodes>, 'droppedNodes' | 'duplicateIds'>;
  mtimeMs: number;
} | null = null;
let EDGES_CACHE: ReturnType<typeof buildCloudEdges> | null = null;

function loadCloudData() {
  // 与 build_cloud.py 输出同源：cloud3d/cloud_data.json（相对 server/ 上溯两级）
  const p = path.join(__dirname, '..', '..', '..', 'cloud3d', 'cloud_data.json');
  try {
    if (fs.existsSync(p)) {
      const mtimeMs = fs.statSync(p).mtimeMs;
      if (CLOUD_CACHE?.mtimeMs === mtimeMs) return CLOUD_CACHE;
      const raw = JSON.parse(fs.readFileSync(p, 'utf-8'));
      const normalized = normalizeCloudNodes(raw.nodes);
      CLOUD_CACHE = {
        nodes: normalized.nodes,
        meta: raw.meta && typeof raw.meta === 'object' ? raw.meta : {},
        diagnostics: {
          droppedNodes: normalized.droppedNodes,
          duplicateIds: normalized.duplicateIds,
        },
        mtimeMs,
      };
      EDGES_CACHE = null;
      return CLOUD_CACHE;
    }
  } catch {
    /* 文件损坏时返回 null，前端会提示加载失败 */
  }
  return null;
}

/** GET /api/cloud/graph — 真实 RAG 派生的云图数据 */
cloudRouter.get('/graph', (_req: AuthRequest, res: Response) => {
  const data = loadCloudData();
  if (!data || !data.nodes.length) {
    res.status(503).json({ message: '云图数据暂不可用，请检查 cloud_data.json' });
    return;
  }
  const nodes = data.nodes;
  // edges 只算一次（与 CLOUD_CACHE 同源），后续请求复用缓存
  EDGES_CACHE = EDGES_CACHE ?? buildCloudEdges(nodes);
  const edges = EDGES_CACHE;
  const legend = (data.meta.legend || []).map((l: any) => ({
    id: l.id,
    name: l.name,
    color: l.color,
    count: l.count,
  }));

  const ragIds = ragData.isReady
    ? new Set(ragData.candidates.map((candidate) => candidate.candidate_id))
    : undefined;
  const sync = assessRagSync(nodes, ragIds);
  const warnings: string[] = [];
  if (sync.status === 'snapshot') warnings.push('RAG 数据未加载，当前显示最近一次生成快照');
  if (sync.status === 'stale') warnings.push('云图与当前 RAG 的 candidate_id 集合不一致，请重新生成云图');
  if (data.diagnostics.droppedNodes > 0) warnings.push(`${data.diagnostics.droppedNodes} 个坐标异常节点已跳过`);
  if (data.diagnostics.duplicateIds > 0) warnings.push(`${data.diagnostics.duplicateIds} 个重复 ID 已跳过`);

  res.setHeader('Cache-Control', 'private, max-age=60');
  res.json({
    nodes,
    edges,
    meta: {
      title: data.meta.title,
      schema_version: data.meta.schema_version ?? 1,
      generated_at: data.meta.generated_at,
      evidence_count: data.meta.evidence_count,
      source_chain: Array.isArray(data.meta.source_chain) ? data.meta.source_chain : [],
      mentor_count: nodes.length,
      domain_count: legend.length,
      legend,
      camera: data.meta.camera,
      classification: data.meta.classification,
      data_status: sync.status,
      rag_count: sync.ragCount,
      missing_from_graph: sync.missingFromGraph,
      orphaned_graph_nodes: sync.orphanedGraphNodes,
      warnings,
    },
  });
});

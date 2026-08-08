import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const cloudRouter = Router();

cloudRouter.use(authMiddleware);

/**
 * 3D 云图数据源：由 cloud3d/build_cloud.py 从 RAG 库生成的银河盘数据。
 * - 节点字段完全来自 cloud_data.json（715 位导师，含 x/y/z 坐标、领域、亮度、大小、论文等）
 * - edges 边数据 cloud_data.json 不含（只有同域星座连线），这里按「同领域最近邻」动态生成，
 *   形成 3D 星图中的关系连线（同域=same-field）。
 */

// ---- 数据加载（启动时读取一次，缓存）----
let CLOUD_CACHE: { nodes: any[]; meta: any } | null = null;
// ---- edges 缓存：与 CLOUD_CACHE 同源，数据未变化时只算一次 ----
let EDGES_CACHE: any[] | null = null;

function loadCloudData() {
  // 与 build_cloud.py 输出同源：cloud3d/cloud_data.json（相对 server/ 上溯两级）
  const p = path.join(__dirname, '..', '..', '..', 'cloud3d', 'cloud_data.json');
  try {
    if (fs.existsSync(p)) {
      const raw = JSON.parse(fs.readFileSync(p, 'utf-8'));
      CLOUD_CACHE = { nodes: raw.nodes || [], meta: raw.meta || {} };
      return CLOUD_CACHE;
    }
  } catch {
    /* 文件损坏时返回 null，前端会提示加载失败 */
  }
  return null;
}

/** 把 cloud_data.json 节点映射为前端 CloudNode */
function toCloudNode(n: any) {
  return {
    id: n.candidate_id ?? n.id,
    name: n.name ?? '',
    department: n.department ?? '',
    tags: n.topics && n.topics.length ? n.topics : undefined,
    domain: n.domain,
    domain_name: n.domain_name,
    color: n.color,
    lum: n.lum,
    core_lum: n.core_lum,
    size: n.size,
    x: n.x,
    y: n.y,
    z: n.z,
    topics: n.topics,
    methods: n.methods,
    pubs: n.pubs,
    pub_count: n.pub_count,
    homepage: n.homepage,
    recruitment: n.recruitment,
    // 前端 CloudPage 展示论文数字，cloud_data.json 用 pub_count
    papers: n.pub_count,
  };
}

/** 生成关系边：每个领域内把星点按坐标最近邻相连（同域 = same-field） */
function buildEdges(nodes: any[]) {
  const edges: any[] = [];
  const byDomain: Record<string, any[]> = {};
  nodes.forEach((n) => {
    const d = n.domain ?? '__none__';
    (byDomain[d] = byDomain[d] || []).push(n);
  });

  const MAX_PER_DOMAIN = 400;
  Object.values(byDomain).forEach((list) => {
    const use = list.slice(0, MAX_PER_DOMAIN);
    for (let i = 0; i < use.length; i++) {
      const a = use[i];
      const ax = a.x ?? 0;
      const ay = a.y ?? 0;
      const az = a.z ?? 0;
      let best: any = null;
      let bestD = Infinity;
      for (let j = 0; j < use.length; j++) {
        if (i === j) continue;
        const b = use[j];
        const dx = ax - (b.x ?? 0);
        const dy = ay - (b.y ?? 0);
        const dz = az - (b.z ?? 0);
        const d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < bestD) {
          bestD = d2;
          best = b;
        }
      }
      if (best) {
        edges.push({
          source: a.candidate_id ?? a.id,
          target: best.candidate_id ?? best.id,
          weight: Math.max(0.1, 1 - Math.sqrt(bestD) / 400),
          relation: 'same-field',
        });
      }
    }
  });
  return edges;
}

/** GET /api/cloud/graph — 云图数据（真实 715 节点） */
cloudRouter.get('/graph', (_req: AuthRequest, res: Response) => {
  const data = CLOUD_CACHE ?? loadCloudData();
  if (!data || !data.nodes.length) {
    res.status(404).json({ message: '云图数据未找到（缺乏 cloud_data.json）' });
    return;
  }
  const nodes = data.nodes.map(toCloudNode);
  // edges 只算一次（与 CLOUD_CACHE 同源），后续请求复用缓存
  EDGES_CACHE = EDGES_CACHE ?? buildEdges(data.nodes);
  const edges = EDGES_CACHE;
  const legend = (data.meta.legend || []).map((l: any) => ({
    id: l.id,
    name: l.name,
    color: l.color,
    count: l.count,
  }));

  res.json({
    nodes,
    edges,
    meta: {
      title: data.meta.title,
      mentor_count: nodes.length,
      domain_count: legend.length,
      legend,
      camera: data.meta.camera,
    },
  });
});
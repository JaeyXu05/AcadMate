export interface CloudGraphNode {
  id: string;
  name: string;
  department: string;
  tags: string[];
  domain: string;
  domain_name: string;
  color: string;
  lum: number;
  core_lum: number;
  size: number;
  x: number;
  y: number;
  z: number;
  topics: string[];
  methods: string[];
  pubs: string[];
  pub_count: number;
  papers: number;
  homepage?: string;
  recruitment?: string;
  classification_status: 'classified' | 'unclassified';
  classification_score: number;
  classification_margin: number;
}

export interface CloudGraphEdge {
  source: string;
  target: string;
  weight: number;
  relation: 'same-field';
}

export interface NormalizedCloudData {
  nodes: CloudGraphNode[];
  droppedNodes: number;
  duplicateIds: number;
}

export type RagSyncStatus = 'ready' | 'stale' | 'snapshot';

export interface RagSyncAssessment {
  status: RagSyncStatus;
  graphCount: number;
  ragCount: number;
  missingFromGraph: number;
  orphanedGraphNodes: number;
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}

function textList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .map((item) => item.trim());
}

function finiteNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/**
 * Runtime boundary for the generated JSON artifact. Invalid IDs/coordinates are
 * excluded instead of silently piling corrupt nodes at the origin.
 */
export function normalizeCloudNodes(rawNodes: unknown): NormalizedCloudData {
  if (!Array.isArray(rawNodes)) return { nodes: [], droppedNodes: 0, duplicateIds: 0 };

  const seen = new Set<string>();
  const nodes: CloudGraphNode[] = [];
  let droppedNodes = 0;
  let duplicateIds = 0;

  for (const raw of rawNodes) {
    if (!raw || typeof raw !== 'object') {
      droppedNodes += 1;
      continue;
    }
    const source = raw as Record<string, unknown>;
    const id = text(source.candidate_id ?? source.id);
    const coordinates = [source.x, source.y, source.z];
    if (!id || coordinates.some((value) => typeof value !== 'number' || !Number.isFinite(value))) {
      droppedNodes += 1;
      continue;
    }
    if (seen.has(id)) {
      duplicateIds += 1;
      continue;
    }
    seen.add(id);

    const topics = textList(source.topics ?? source.tags);
    const pubCount = Math.max(0, Math.round(finiteNumber(source.pub_count ?? source.papers, 0)));
    const classificationStatus = source.classification_status === 'unclassified'
      ? 'unclassified'
      : 'classified';

    nodes.push({
      id,
      name: text(source.name, '未命名导师'),
      department: text(source.department, '院系待补充'),
      tags: topics,
      domain: text(source.domain, 'unclassified'),
      domain_name: text(source.domain_name, '待分类'),
      color: text(source.color, '#a7b0c0'),
      lum: Math.min(1, Math.max(0.2, finiteNumber(source.lum, 0.65))),
      core_lum: Math.min(1, Math.max(0, finiteNumber(source.core_lum, 0))),
      size: Math.min(5, Math.max(0.8, finiteNumber(source.size, 1))),
      x: source.x as number,
      y: source.y as number,
      z: source.z as number,
      topics,
      methods: textList(source.methods),
      pubs: textList(source.pubs),
      pub_count: pubCount,
      papers: pubCount,
      homepage: text(source.homepage) || undefined,
      recruitment: text(source.recruitment) || undefined,
      classification_status: classificationStatus,
      classification_score: Math.max(0, finiteNumber(source.classification_score, 0)),
      classification_margin: Math.max(0, finiteNumber(source.classification_margin, 0)),
    });
  }

  return { nodes, droppedNodes, duplicateIds };
}

/** One nearest-neighbour relation per node, deduplicated as undirected pairs. */
export function buildCloudEdges(nodes: CloudGraphNode[]): CloudGraphEdge[] {
  const byDomain = new Map<string, CloudGraphNode[]>();
  for (const node of nodes) {
    const group = byDomain.get(node.domain) ?? [];
    group.push(node);
    byDomain.set(node.domain, group);
  }

  const edges: CloudGraphEdge[] = [];
  const pairs = new Set<string>();
  const maxPerDomain = 400;

  for (const group of byDomain.values()) {
    const candidates = group.slice(0, maxPerDomain);
    for (let index = 0; index < candidates.length; index += 1) {
      const source = candidates[index];
      let nearest: CloudGraphNode | undefined;
      let nearestDistanceSquared = Number.POSITIVE_INFINITY;

      for (let otherIndex = 0; otherIndex < candidates.length; otherIndex += 1) {
        if (index === otherIndex) continue;
        const target = candidates[otherIndex];
        const dx = source.x - target.x;
        const dy = source.y - target.y;
        const dz = source.z - target.z;
        const distanceSquared = dx * dx + dy * dy + dz * dz;
        if (distanceSquared < nearestDistanceSquared) {
          nearestDistanceSquared = distanceSquared;
          nearest = target;
        }
      }

      if (!nearest) continue;
      const [first, second] = [source.id, nearest.id].sort();
      const pair = `${first}\u0000${second}`;
      if (pairs.has(pair)) continue;
      pairs.add(pair);
      edges.push({
        source: source.id,
        target: nearest.id,
        weight: Math.max(0.1, 1 - Math.sqrt(nearestDistanceSquared) / 400),
        relation: 'same-field',
      });
    }
  }

  return edges;
}

export function assessRagSync(nodes: CloudGraphNode[], ragIds?: ReadonlySet<string>): RagSyncAssessment {
  if (!ragIds) {
    return {
      status: 'snapshot',
      graphCount: nodes.length,
      ragCount: 0,
      missingFromGraph: 0,
      orphanedGraphNodes: 0,
    };
  }

  const graphIds = new Set(nodes.map((node) => node.id));
  let missingFromGraph = 0;
  let orphanedGraphNodes = 0;
  for (const id of ragIds) if (!graphIds.has(id)) missingFromGraph += 1;
  for (const id of graphIds) if (!ragIds.has(id)) orphanedGraphNodes += 1;

  return {
    status: missingFromGraph === 0 && orphanedGraphNodes === 0 ? 'ready' : 'stale',
    graphCount: nodes.length,
    ragCount: ragIds.size,
    missingFromGraph,
    orphanedGraphNodes,
  };
}

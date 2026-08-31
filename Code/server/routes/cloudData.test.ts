import assert from 'node:assert/strict';
import test from 'node:test';

import { assessRagSync, buildCloudEdges, normalizeCloudNodes } from './cloudData.ts';

const rawNodes = [
  { candidate_id: 'a', name: '甲', domain: 'cs', domain_name: '计算机', x: 0, y: 0, z: 0 },
  { candidate_id: 'b', name: '乙', domain: 'cs', domain_name: '计算机', x: 2, y: 0, z: 0 },
  { candidate_id: 'c', name: '丙', domain: 'cs', domain_name: '计算机', x: 8, y: 0, z: 0 },
];

test('normalization rejects invalid and duplicate IDs while preserving safe fallbacks', () => {
  const result = normalizeCloudNodes([
    ...rawNodes,
    { candidate_id: 'a', x: 1, y: 1, z: 1 },
    { candidate_id: 'bad', x: Number.NaN, y: 1, z: 1 },
  ]);
  assert.equal(result.nodes.length, 3);
  assert.equal(result.duplicateIds, 1);
  assert.equal(result.droppedNodes, 1);
  assert.equal(result.nodes[0].department, '院系待补充');
  assert.deepEqual(result.nodes[0].tags, []);
});

test('nearest-neighbour edges are undirected and deduplicated', () => {
  const { nodes } = normalizeCloudNodes(rawNodes);
  const edges = buildCloudEdges(nodes);
  assert.deepEqual(edges.map(({ source, target }) => [source, target]), [['a', 'b'], ['c', 'b']]);
  assert.equal(new Set(edges.map((edge) => [edge.source, edge.target].sort().join(':'))).size, edges.length);
});

test('RAG sync reports ready, stale, and snapshot states', () => {
  const { nodes } = normalizeCloudNodes(rawNodes);
  assert.equal(assessRagSync(nodes, new Set(['a', 'b', 'c'])).status, 'ready');
  const stale = assessRagSync(nodes, new Set(['a', 'b', 'd']));
  assert.equal(stale.status, 'stale');
  assert.equal(stale.missingFromGraph, 1);
  assert.equal(stale.orphanedGraphNodes, 1);
  assert.equal(assessRagSync(nodes).status, 'snapshot');
});

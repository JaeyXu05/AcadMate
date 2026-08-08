import assert from 'node:assert/strict';
import { buildWindowTimeline } from '../src/features/tasks/windowTimeline.ts';

const baseWindow = (patch) => ({
  id: patch.id,
  subscription_id: 1,
  query_snapshot: 'cat:cs.AI',
  job_id: 1,
  kind: patch.kind ?? 'daily',
  window_start: patch.window_start,
  window_end: patch.window_end,
  status: patch.status ?? 'succeeded',
  total_results: patch.total_results ?? null,
  fetched_count: patch.fetched_count ?? 0,
  inserted_count: patch.inserted_count ?? 0,
  updated_count: patch.updated_count ?? 0,
  page_size: 100,
  page_count: 1,
  error_message: patch.error_message ?? null,
  warning_code: patch.warning_code ?? null,
  parent_window_id: null,
  started_at: patch.window_start,
  finished_at: patch.window_end,
  created_at: patch.window_start,
  updated_at: patch.window_end,
});

const timeline = buildWindowTimeline([
  baseWindow({ id: 3, window_start: '2024-01-03T00:00:00Z', window_end: '2024-01-04T00:00:00Z', fetched_count: 30 }),
  baseWindow({ id: 1, window_start: '2024-01-01T00:00:00Z', window_end: '2024-01-02T00:00:00Z', fetched_count: 10 }),
  baseWindow({ id: 2, window_start: '2024-01-02T00:00:00Z', window_end: '2024-01-03T00:00:00Z', fetched_count: 20 }),
  baseWindow({ id: 4, status: 'failed', window_start: '2024-01-04T00:00:00Z', window_end: '2024-01-05T00:00:00Z', error_message: 'boom' }),
  baseWindow({ id: 5, window_start: '2024-01-06T00:00:00Z', window_end: '2024-01-07T00:00:00Z', fetched_count: 40 }),
]);

assert.equal(timeline.summary.totalWindows, 5);
assert.equal(timeline.summary.coverageStart, '2024-01-01T00:00:00Z');
assert.equal(timeline.summary.coverageEnd, '2024-01-07T00:00:00Z');
assert.equal(timeline.summary.issueCount, 1);
assert.equal(timeline.summary.successSegmentCount, 2);
assert.deepEqual(timeline.segments.map((segment) => segment.kind), ['success', 'issue', 'gap', 'success']);
assert.equal(timeline.segments[0].windowIds.join(','), '1,2,3');
assert.equal(timeline.segments[0].fetchedCount, 60);
assert.equal(timeline.segments[0].intensity, 0.75);
assert.equal(timeline.segments[1].status, 'failed');
assert.equal(timeline.segments[2].kind, 'gap');
assert.equal(timeline.segments[3].intensity, 1);
assert.equal(timeline.details[0].id, 4);
assert.equal(timeline.details[1].id, 5);

const recoveredTimeline = buildWindowTimeline([
  baseWindow({ id: 10, status: 'failed', window_start: '2024-02-01T00:00:00Z', window_end: '2024-02-02T00:00:00Z', error_message: 'temporary arXiv failure' }),
  baseWindow({ id: 11, kind: 'history', window_start: '2024-02-01T00:00:00Z', window_end: '2024-02-02T00:00:00Z', fetched_count: 12 }),
  baseWindow({ id: 12, window_start: '2024-02-02T00:00:00Z', window_end: '2024-02-03T00:00:00Z', fetched_count: 8 }),
]);

assert.equal(recoveredTimeline.summary.totalWindows, 2);
assert.equal(recoveredTimeline.summary.issueCount, 0);
assert.deepEqual(recoveredTimeline.segments.map((segment) => segment.kind), ['success']);
assert.deepEqual(recoveredTimeline.segments[0].windowIds, [11, 12]);
assert.deepEqual(recoveredTimeline.details.map((window) => window.id), [12, 11]);

const recheckedTimeline = buildWindowTimeline([
  baseWindow({ id: 20, window_start: '2024-03-01T00:00:00Z', window_end: '2024-03-02T00:00:00Z', fetched_count: 0 }),
  baseWindow({ id: 21, kind: 'history', window_start: '2024-03-01T00:00:00Z', window_end: '2024-03-02T00:00:00Z', fetched_count: 6, inserted_count: 2 }),
  baseWindow({ id: 22, window_start: '2024-03-02T00:00:00Z', window_end: '2024-03-03T00:00:00Z', fetched_count: 4 }),
]);

assert.equal(recheckedTimeline.summary.totalWindows, 2);
assert.deepEqual(recheckedTimeline.segments.map((segment) => segment.kind), ['success']);
assert.deepEqual(recheckedTimeline.segments[0].windowIds, [21, 22]);
assert.equal(recheckedTimeline.segments[0].fetchedCount, 10);
assert.deepEqual(recheckedTimeline.details.map((window) => window.id), [22, 21]);

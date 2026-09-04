import test from 'node:test';
import assert from 'node:assert/strict';
import { cleanTopics } from './topicBoilerplate';

test('topic cleaning preserves useful clauses before narrative text', () => {
  const result = cleanTopics(['凝聚态物理。专注于发展飞秒时间与亚纳米空间分辨的精密测量新方法']);
  assert.ok(result.includes('凝聚态物理'));
  assert.ok(result.some((item) => item.includes('飞秒时间')));
});

test('topic cleaning preserves long English research directions', () => {
  const topic = 'Numerical solutions of nonlinear wave equations using local discontinuous Galerkin methods';
  assert.deepEqual(cleanTopics([topic]), [topic]);
});

test('topic cleaning still removes navigation, recruitment and contact noise', () => {
  assert.deepEqual(cleanTopics([
    '招生须知',
    '版权所有 中国科学技术大学',
    '邮编：230026',
    '欢迎优秀学生加入团队',
    'https://example.com/profile',
    'an adjunct professor of UMass Amherst from 2016 to 2019',
    'University of Science and Technology of China',
    '“Upgrading glycerol to sorbose via a tandem photoelectrocatalysis relay”',
    '量子计算',
  ]), ['量子计算']);
});

test('topic cleaning strips research-introduction prefixes instead of deleting content', () => {
  assert.deepEqual(cleanTopics([
    'My current research interest mainly focus on novel simulation techniques',
    '专注于发展飞秒时间分辨的精密测量新方法',
  ]), [
    'novel simulation techniques',
    '发展飞秒时间分辨的精密测量新方法',
  ]);
});

test('topic cleaning splits semicolon lists and keeps stable unique order', () => {
  assert.deepEqual(
    cleanTopics(['计算机视觉；多模态生成;计算机视觉']),
    ['计算机视觉', '多模态生成'],
  );
});

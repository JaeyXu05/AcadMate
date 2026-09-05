import assert from 'node:assert/strict';
import test from 'node:test';

import {
  RESEARCH_ASSISTANT_INSTRUCTIONS,
  explainResearchProfileError,
  explainResearchStreamError,
  researchAgentOverrides,
  researchProfileTimeoutMs,
  researchAgentTimeoutMs,
} from './researchRuntime';

test('research chat keeps a bounded interactive output budget without retries', () => {
  assert.deepEqual(researchAgentOverrides('research'), {
    max_tokens: 1200,
    timeout: 90,
    max_retries: 0,
    extra_body: { thinking: { type: 'disabled' } },
  });
  assert.deepEqual(researchAgentOverrides('search'), {});
  assert.equal(researchAgentTimeoutMs({}), 180_000);
  assert.equal(researchAgentTimeoutMs({ RESEARCH_AGENT_TIMEOUT_MS: '20000' }), 20_000);
  assert.equal(researchAgentTimeoutMs({ RESEARCH_AGENT_TIMEOUT_MS: '60000' }), 60_000);
  assert.equal(researchProfileTimeoutMs({}), 300_000);
  assert.equal(researchProfileTimeoutMs({ RESEARCH_PROFILE_TIMEOUT_MS: '240000' }), 240_000);
});

test('research prompt requires readable, evidence-bounded output', () => {
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /自然、直接的中文/);
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /交付物和验收标准/);
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /不输出内部思维链/);
});

test('timeout errors become an actionable Chinese message', () => {
  const result = explainResearchStreamError(new DOMException('aborted', 'AbortError'));
  assert.equal(result.timedOut, true);
  assert.match(result.message, /180 秒/);
  assert.match(result.message, /部分内容会保留/);
  assert.match(explainResearchStreamError(new DOMException('aborted', 'AbortError'), 60_000).message, /60 秒/);
});

test('upstream connection failures become actionable without exposing credentials', () => {
  const result = explainResearchStreamError(new Error("couldn't get a connection after 30.00 sec"));
  assert.equal(result.timedOut, false);
  assert.match(result.message, /网关连接失败/);
  assert.doesNotMatch(result.message, /30\.00/);
  assert.match(
    explainResearchStreamError(new Error('InternalServerError: upstream connect error or disconnect/reset before headers. reset reason: connection termination')).message,
    /网关连接失败/,
  );
});

test('upstream authentication and model errors get distinct guidance', () => {
  assert.match(explainResearchStreamError(new Error('401 Unauthorized')).message, /鉴权失败/);
  assert.match(explainResearchStreamError(new Error('api_key_unavailable')).message, /鉴权失败/);
  assert.match(explainResearchStreamError(new Error('configured_model_unavailable')).message, /模型或接口不存在/);
});

test('research profile maps gateway reset and timeout failures', () => {
  const reset = explainResearchProfileError(new Error('InternalServerError: upstream connect error or disconnect/reset before headers. reset reason: connection termination'));
  assert.equal(reset.timedOut, false);
  assert.match(reset.message, /画像模型网关连接失败/);
  assert.match(explainResearchProfileError(new DOMException('aborted', 'AbortError')).message, /300 秒/);
});

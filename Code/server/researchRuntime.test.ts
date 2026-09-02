import assert from 'node:assert/strict';
import test from 'node:test';

import {
  RESEARCH_ASSISTANT_INSTRUCTIONS,
  explainResearchStreamError,
  researchAgentOverrides,
  researchAgentTimeoutMs,
} from './researchRuntime';

test('research chat uses a bounded, zero-retry model call', () => {
  assert.deepEqual(researchAgentOverrides('research'), {
    max_tokens: 2200,
    timeout: 35,
    max_retries: 0,
  });
  assert.deepEqual(researchAgentOverrides('search'), {});
  assert.equal(researchAgentTimeoutMs({}), 75_000);
  assert.equal(researchAgentTimeoutMs({ RESEARCH_AGENT_TIMEOUT_MS: '60000' }), 60_000);
});

test('research prompt requires readable, evidence-bounded output', () => {
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /自然、直接的中文/);
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /交付物和验收标准/);
  assert.match(RESEARCH_ASSISTANT_INSTRUCTIONS, /不输出内部思维链/);
});

test('timeout errors become an actionable Chinese message', () => {
  const result = explainResearchStreamError(new DOMException('aborted', 'AbortError'));
  assert.equal(result.timedOut, true);
  assert.match(result.message, /75 秒/);
  assert.match(result.message, /部分内容会保留/);
  assert.match(explainResearchStreamError(new DOMException('aborted', 'AbortError'), 60_000).message, /60 秒/);
});

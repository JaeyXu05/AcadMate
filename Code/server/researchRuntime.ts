export const RESEARCH_ASSISTANT_INSTRUCTIONS = `
你正在科研工作台回答用户。请使用自然、直接的中文，像一位认真但不端着的科研搭档。

输出要求：
1. 先回答用户真正问的事，不复述问题，不输出内部思维链、路由过程或 Agent 日志。
2. 普通讨论直接回答；只有需要外部论文事实时才调用检索/论文工具，不要为了展示多智能体而无意义地层层委派。
3. 研究建议按“当前判断—证据或缺口—下一步”组织。下一步必须说明交付物和验收标准，禁止只写“多读论文、继续学习、提升能力”。
4. 引用论文结论时绑定可见证据；检索失败或证据不足时明确说未知，并给出仍可执行的下一步。
5. 工具或某个专门 Agent 超时后，用已经获得的证据给出部分结果，不要让用户只看到空白或报错码。
6. 默认控制在 600 个中文字符内；用户明确要求长文时除外。
`.trim();

const DEFAULT_RESEARCH_TIMEOUT_MS = 180_000;
const DEFAULT_RESEARCH_PROFILE_TIMEOUT_MS = 300_000;

export function researchAgentTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const configured = Number(env.RESEARCH_AGENT_TIMEOUT_MS);
  return Number.isFinite(configured) && configured >= 10_000 ? configured : DEFAULT_RESEARCH_TIMEOUT_MS;
}

export function researchProfileTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const configured = Number(env.RESEARCH_PROFILE_TIMEOUT_MS);
  return Number.isFinite(configured) && configured >= 30_000 ? configured : DEFAULT_RESEARCH_PROFILE_TIMEOUT_MS;
}

export function researchAgentOverrides(surface: string): {
  max_tokens?: number;
  timeout?: number;
  max_retries?: number;
  extra_body?: Record<string, unknown>;
} {
  if (surface !== 'research') return {};
  // Keep the interactive path bounded. The UI asks for a concise answer, and
  // disabling provider-side hidden reasoning avoids spending most of the
  // request budget before the first visible token on gateways that support it.
  // Do not retry a synchronous chat request: a retry doubles the visible wait
  // when the gateway is slow or temporarily unavailable.
  return {
    max_tokens: 1200,
    timeout: 90,
    max_retries: 0,
    extra_body: { thinking: { type: 'disabled' } },
  };
}

export function explainResearchStreamError(
  error: unknown,
  timeoutMs = researchAgentTimeoutMs(),
): { timedOut: boolean; message: string } {
  const raw = error instanceof Error ? error.message : String(error || '');
  const gatewayTimeout = /connecttimeout|readtimeout|handshake.*timed out|connection.*timed out/i.test(raw);
  const timedOut = !gatewayTimeout && error instanceof Error && (
    error.name === 'AbortError' || /abort|timeout/i.test(error.message)
  );
  if (timedOut) {
    return {
      timedOut: true,
      message: `这次科研处理超过 ${Math.round(timeoutMs / 1000)} 秒，已自动停止。已生成的部分内容会保留；请缩小问题范围或先在右侧选择一篇论文再试。`,
    };
  }
  if (/couldn't get a connection|upstream connect error|disconnect\/reset|connection termination|connection reset|connection refused|connecttimeout|readtimeout|handshake.*timed out|connection.*timed out|chat_gateway_unreachable|pooltimeout|connecterror|fetch failed|econnrefused|enotfound|econnreset|ehostunreach|network is unreachable|tls|ssl/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研模型网关连接失败。请检查当前网络、Base URL 及代理设置；API Key 保存成功并不代表上游网关当前可达。',
    };
  }
  if (/401|403|unauthorized|invalid.*(api|key)|api[\s_-]?key.*(invalid|missing|unavailable)|authentication/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研模型 API 鉴权失败。请确认 API Key 有效，并确认它属于当前 Base URL 对应的服务。',
    };
  }
  if (/404|model.*(not found|unavailable)|configured_model_unavailable/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研模型或接口不存在。请检查 Base URL 是否为 OpenAI 兼容接口地址，以及模型名称是否准确。',
    };
  }
  return {
    timedOut: false,
    message: error instanceof Error ? error.message : 'PAPERCLAW Agent 调用失败',
  };
}

export function explainResearchProfileError(
  error: unknown,
  timeoutMs = researchProfileTimeoutMs(),
): { timedOut: boolean; message: string } {
  const raw = error instanceof Error ? error.message : String(error || '');
  const timedOut = error instanceof Error && (
    error.name === 'AbortError' || /abort|timeout|timed out/i.test(error.message)
  );
  if (timedOut) {
    return {
      timedOut: true,
      message: `科研画像生成超过 ${Math.round(timeoutMs / 1000)} 秒，已自动停止；已有画像和个人资料不会丢失，请稍后重试。`,
    };
  }
  if (/couldn't get a connection|upstream connect error|disconnect\/reset|connection termination|connection reset|connection refused|pooltimeout|connecterror|fetch failed|econnrefused|enotfound|econnreset|ehostunreach|network is unreachable|tls|ssl/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研画像模型网关连接失败。请检查当前网络、Base URL 及代理设置；API Key 保存成功并不代表上游网关当前可达。',
    };
  }
  if (/401|403|unauthorized|invalid.*(api|key)|api[\s_-]?key.*(invalid|missing|unavailable)|authentication/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研画像模型 API 鉴权失败。请确认 API Key 有效，并确认它属于当前 Base URL 对应的服务。',
    };
  }
  if (/404|model.*(not found|unavailable)|configured_model_unavailable/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研画像模型或接口不存在。请检查 Base URL 是否为 OpenAI 兼容接口地址，以及模型名称是否准确。',
    };
  }
  if (/model.*not set|chat_model_missing/i.test(raw)) {
    return {
      timedOut: false,
      message: '科研画像需要模型服务，请先在环境配置中填写聊天模型后再试。',
    };
  }
  return {
    timedOut: false,
    message: error instanceof Error ? error.message : '科研画像生成失败',
  };
}

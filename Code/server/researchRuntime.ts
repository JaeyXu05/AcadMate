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

export function researchAgentTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const configured = Number(env.RESEARCH_AGENT_TIMEOUT_MS);
  return Number.isFinite(configured) && configured >= 10_000 ? configured : 75_000;
}

export function researchAgentOverrides(surface: string): {
  max_tokens?: number;
  timeout?: number;
  max_retries?: number;
} {
  if (surface !== 'research') return {};
  return { max_tokens: 2200, timeout: 35, max_retries: 0 };
}

export function explainResearchStreamError(
  error: unknown,
  timeoutMs = researchAgentTimeoutMs(),
): { timedOut: boolean; message: string } {
  const timedOut = error instanceof Error && (
    error.name === 'AbortError' || /abort|timeout/i.test(error.message)
  );
  if (timedOut) {
    return {
      timedOut: true,
      message: `这次科研处理超过 ${Math.round(timeoutMs / 1000)} 秒，已自动停止。已生成的部分内容会保留；请缩小问题范围或先在右侧选择一篇论文再试。`,
    };
  }
  return {
    timedOut: false,
    message: error instanceof Error ? error.message : 'PAPERCLAW Agent 调用失败',
  };
}

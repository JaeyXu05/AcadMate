import {
  enqueuePendingGrowthWrite,
  loadTrustedAgentContext,
  updatePendingGrowthWrite,
  writeReviewedGrowth,
  type ReviewedGrowthWrite,
} from './data/growthStore';
import { saveRunArtifact } from './data/runArtifacts';

export function agentBase(): string {
  return String(process.env.MENTOR_AGENT_BASE_URL || '').replace(/\/+$/, '');
}

export function agentTimeoutMs(): number {
  // Mentor workflow contains two model calls which can each approach the
  // configured 120s upstream timeout.  Keep enough headroom for polling and
  // review instead of falling back while A is still working.
  return Number(process.env.MENTOR_AGENT_TIMEOUT_MS) || 420000;
}

export function agentPollMs(): number {
  return Number(process.env.MENTOR_AGENT_POLL_MS) || 1200;
}

export function agentUrl(path: string): string {
  return `${agentBase()}${path}`;
}

export async function probeAgent(timeoutMs = 2500): Promise<boolean> {
  const base = agentBase();
  if (!base) return false;
  try {
    // Mentor search can run in deterministic mode without a chat provider.
    // Probe its scoped readiness instead of the whole Paper Claw model stack.
    const res = await fetch(agentUrl('/api/mentor-ready'), { signal: AbortSignal.timeout(timeoutMs) });
    if (!res.ok) return false;
    const payload = await res.json().catch(() => ({}));
    return payload?.ready !== false;
  } catch {
    return false;
  }
}

/** Liveness is intentionally separate from model readiness.  A slow gateway
 * must not make the D side invent a local fallback before A has a chance to
 * execute and record the real model result. */
export async function probeAgentLiveness(timeoutMs = 2500): Promise<boolean> {
  const base = agentBase();
  if (!base) return false;
  try {
    const res = await fetch(agentUrl('/api/health'), { signal: AbortSignal.timeout(timeoutMs) });
    return res.ok;
  } catch { return false; }
}

function isAgentUnreachable(err: unknown): boolean {
  const parts: string[] = [];
  if (err instanceof Error) {
    parts.push(err.name, err.message);
    const cause = (err as Error & { cause?: unknown }).cause;
    if (cause instanceof Error) parts.push(cause.name, cause.message);
    else if (cause) parts.push(String(cause));
  } else if (err) {
    parts.push(String(err));
  }
  const blob = parts.join(' ').toLowerCase();
  return (
    blob.includes('fetch failed') ||
    blob.includes('econnrefused') ||
    blob.includes('enotfound') ||
    blob.includes('econnreset') ||
    blob.includes('ehostunreach') ||
    blob.includes('connect timeout') ||
    blob.includes('other side closed')
  );
}

function isAgentTimeout(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  const name = String((err as { name?: string }).name || '');
  const msg = String((err as { message?: string }).message || '').toLowerCase();
  return name === 'TimeoutError' || name === 'AbortError' || msg.includes('timeout') || msg.includes('aborted');
}

/** 把连 A 端失败的 undici「fetch failed」收成可读中文，避免原样冒到 PDF 分析页。 */
export function explainAgentError(err: unknown, fallback: string): Error {
  const base = agentBase() || 'http://127.0.0.1:8000';
  if (isAgentTimeout(err) && !isAgentUnreachable(err)) {
    const wrapped = new Error(`Mentor Agent 响应超时（${base}）。请确认 A 端已启动且负载正常后重试。`);
    (wrapped as Error & { status?: number }).status = 504;
    return wrapped;
  }
  if (isAgentUnreachable(err)) {
    const wrapped = new Error(
      `Mentor Agent 未启动或无法连接（${base}）。PDF 已保存在本服务；分析需要先启动 A 端后再点「开始分析」。`,
    );
    (wrapped as Error & { status?: number }).status = 503;
    return wrapped;
  }
  if (err instanceof Error) return err;
  const wrapped = new Error(fallback);
  (wrapped as Error & { status?: number }).status = 503;
  return wrapped;
}

export function isNumericRunId(value: unknown): value is string {
  return typeof value === 'string' && /^\d+$/.test(value);
}

export function suggestNextSkill(growth: Record<string, unknown> | null | undefined): string | null {
  const payload = growth || {};
  const matched = Array.isArray(payload.matched_mentors) ? payload.matched_mentors : [];
  const readPapers = Array.isArray(payload.read_papers) ? payload.read_papers : [];
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
  const hypotheses = Array.isArray(payload.direction_hypotheses) ? payload.direction_hypotheses : [];
  const pending = (Array.isArray(payload.research_tasks) ? payload.research_tasks : []).filter((item) => {
    if (!item || typeof item !== 'object') return false;
    const status = String((item as { status?: unknown }).status || '');
    return status === 'pending' || status === 'in_progress';
  }) as Array<{ id?: unknown }>;

  if (matched.length && !readPapers.length) return 'paper_qa';
  if (pending.some((item) => String(item.id || '').startsWith('read-mentor:'))) return 'paper_qa';
  if (matched.length && !hypotheses.length) return 'direction_explore';
  if (pending.some((item) => String(item.id || '').startsWith('research-question:'))) return 'research_task';
  if (readPapers.length && !artifacts.some((item) => item && typeof item === 'object' && (item as { type?: unknown }).type === 'contact_email')) {
    return 'email_compose';
  }
  if (artifacts.some((item) => item && typeof item === 'object' && (item as { type?: unknown }).type === 'pdf_document' && (item as { status?: unknown }).status === 'uploaded')) {
    return 'pdf_analyze';
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function postHarnessRun(body: Record<string, unknown>, timeoutMs = agentTimeoutMs()): Promise<any> {
  const base = agentBase();
  if (!base) {
    const err = new Error('未配置 MENTOR_AGENT_BASE_URL');
    (err as Error & { status?: number }).status = 503;
    throw err;
  }
  let runRes: Response;
  try {
    runRes = await fetch(agentUrl('/api/runs'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    throw explainAgentError(err, 'Harness Skill 启动失败');
  }
  if (!runRes.ok) {
    const txt = await runRes.text().catch(() => '');
    const err = new Error(txt.slice(0, 300) || 'Harness Skill 启动失败');
    (err as Error & { status?: number }).status = runRes.status;
    throw err;
  }
  return runRes.json();
}

export async function pollHarnessResult(runId: string, created?: any, timeoutMs = agentTimeoutMs()): Promise<any> {
  const terminal = new Set(['succeeded', 'failed', 'cancelled', 'waiting_for_user']);
  const deadline = Date.now() + timeoutMs;
  let result = created;
  while (Date.now() < deadline) {
    if (terminal.has(String(result?.status || ''))) return result;
    await sleep(agentPollMs());
    const resultRes = await fetch(agentUrl(`/api/runs/${runId}/harness-result`), {
      signal: AbortSignal.timeout(Math.max(agentPollMs() * 2, 5000)),
    });
    if (!resultRes.ok) {
      const txt = await resultRes.text().catch(() => '');
      const err = new Error(txt.slice(0, 300) || '读取 Harness 结果失败');
      (err as Error & { status?: number }).status = resultRes.status;
      throw err;
    }
    result = await resultRes.json();
  }
  const err = new Error('Harness AgentRun 超时，后台将在完成后补写成长状态');
  (err as Error & { status?: number }).status = 504;
  throw err;
}

/** Start an asynchronous Harness run without tying the browser request to model latency. */
export async function launchHarnessSkill(input: {
  userId: number; skillId: string; message: string; context: Record<string, unknown>; timeoutMs?: number;
}): Promise<any> {
  const trusted = loadTrustedAgentContext(input.userId);
  const created = await postHarnessRun({
    skill_id: input.skillId,
    message: input.message,
    context: {
      ...input.context,
      user_id: String(input.userId),
      growth: input.context.growth ?? trusted.growth,
      profile: input.context.profile ?? trusted.profile,
    },
  }, input.timeoutMs ?? 15_000);
  if (!isNumericRunId(String(created?.run_id || ''))) {
    const err = new Error(`${input.skillId} 未返回有效 AgentRun id`);
    (err as Error & { status?: number }).status = 502;
    throw err;
  }
  return created;
}

export async function fetchHarnessResult(runId: string): Promise<any> {
  const response = await fetch(agentUrl(`/api/runs/${runId}/harness-result`), { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error((await response.text().catch(() => '')).slice(0, 300) || '读取 Harness 结果失败');
  return response.json();
}

export async function fetchHarnessEvents(runId: string, afterSequence?: number): Promise<any[]> {
  const suffix = afterSequence ? `?after_sequence=${afterSequence}` : '';
  const response = await fetch(agentUrl(`/api/runs/${runId}/events${suffix}`), { signal: AbortSignal.timeout(10_000) });
  if (!response.ok) return [];
  const payload = await response.json();
  return Array.isArray(payload) ? payload : [];
}

export async function cancelHarnessRun(runId: string): Promise<any> {
  const response = await fetch(agentUrl(`/api/runs/${runId}/cancel`), { method: 'POST', signal: AbortSignal.timeout(10_000) });
  if (!response.ok) throw new Error((await response.text().catch(() => '')).slice(0, 300) || '取消 Harness 任务失败');
  return response.json();
}

export function paperGrowthPatch(runId: string, candidateId: string, result: any): ReviewedGrowthWrite['patch'] {
  const artifact = result?.artifact ?? {};
  const evidenceRefs = Array.isArray(result?.evidence_refs) ? result.evidence_refs : [];
  const tasks = Array.isArray(artifact?.research_tasks) ? artifact.research_tasks : [];
  return {
    read_papers: [{
      paper_id: artifact.paper_id,
      candidate_id: candidateId,
      mentor_name: artifact.mentor_name,
      titles: artifact.publications ?? [],
      evidence_refs: evidenceRefs,
      review_status: 'PASS',
      read_at: new Date().toISOString(),
    }],
    verified_experiences: [{
      id: `paper-reading:${runId}`,
      type: 'paper_reading',
      summary: `完成 ${artifact.mentor_name || candidateId} 论文的证据阅读`,
      evidence_refs: evidenceRefs,
      verified_at: new Date().toISOString(),
    }],
    artifacts: [{
      id: `paper-reading:${runId}`,
      type: 'paper_claw_reading',
      title: artifact.publications?.[0] || 'Paper Claw 阅读结果',
      paper_id: artifact.paper_id,
      evidence_refs: evidenceRefs,
    }],
    research_tasks: [
      {
        id: `read-mentor:${candidateId}`,
        title: `阅读 ${artifact.mentor_name || candidateId} 的代表论文`,
        status: 'completed',
        acceptance_criteria: ['至少形成 2 条论文证据', '记录一个可继续研究的问题'],
        evidence_refs: evidenceRefs,
      },
      ...tasks,
    ],
  };
}

export function pdfGrowthPatch(runId: string, documentId: string, result: any): ReviewedGrowthWrite['patch'] {
  const artifact = result?.artifact ?? {};
  const advisors = Array.isArray(artifact.advisors) ? artifact.advisors : [];
  const evidenceRefs = Array.isArray(result?.evidence_refs) ? result.evidence_refs : [];
  return {
    artifacts: [{
      id: `pdf-analyze:${runId}`,
      type: 'pdf_analyze_result',
      title: documentId,
      document_id: documentId,
      mentor_ids: advisors.map((item: any) => item.id),
      evidence_refs: evidenceRefs,
    }],
    verified_experiences: [{
      id: `pdf-analyze:${runId}`,
      type: 'pdf_analyze',
      summary: `完成文档 ${documentId} 的页级证据分析`,
      evidence_refs: evidenceRefs,
      verified_at: new Date().toISOString(),
    }],
  };
}

export function emailGrowthPatch(runId: string, candidateId: string, result: any): ReviewedGrowthWrite['patch'] {
  const artifact = result?.artifact ?? {};
  const evidenceRefs = Array.isArray(result?.evidence_refs) ? result.evidence_refs : [];
  return {
    artifacts: [{
      id: `contact-email:${runId}`,
      type: 'contact_email',
      title: artifact.subject || '联系邮件草稿',
      candidate_id: candidateId,
      evidence_refs: evidenceRefs,
    }],
    verified_experiences: [{
      id: `contact-email:${runId}`,
      type: 'contact_email',
      summary: `生成联系 ${candidateId} 的已审核邮件草稿`,
      evidence_refs: evidenceRefs,
      verified_at: new Date().toISOString(),
    }],
  };
}

export function commitHarnessPass(input: {
  userId: number;
  runId: string;
  skillId: string;
  query: string;
  result: any;
  patch: ReviewedGrowthWrite['patch'];
  pendingId?: number;
  traceId?: string | null;
}): void {
  if (!isNumericRunId(input.runId) || input.result?.review_status !== 'PASS') {
    throw new Error('成长状态只接受数值 AgentRun 的 Review PASS 结果');
  }
  writeReviewedGrowth(input.userId, {
    runId: input.runId,
    skillId: input.skillId,
    reviewStatus: 'PASS',
    patch: input.patch,
  });
  saveRunArtifact({
    userId: input.userId,
    runId: input.runId,
    traceId: input.traceId,
    skillId: input.skillId,
    query: input.query,
    reviewStatus: 'PASS',
    payload: input.result,
  });
  if (input.pendingId) updatePendingGrowthWrite(input.pendingId, { status: 'written', runId: input.runId });
}

export async function runHarnessSkill(input: {
  userId: number;
  skillId: string;
  message: string;
  context: Record<string, unknown>;
  query?: string;
  timeoutMs?: number;
  patcher?: (runId: string, result: any) => ReviewedGrowthWrite['patch'];
}): Promise<any> {
  const trusted = loadTrustedAgentContext(input.userId);
  const timeoutMs = input.timeoutMs ?? agentTimeoutMs();
  const created = await postHarnessRun({
    skill_id: input.skillId,
    message: input.message,
    context: {
      ...input.context,
      user_id: String(input.userId),
      growth: input.context.growth ?? trusted.growth,
      profile: input.context.profile ?? trusted.profile,
    },
  }, timeoutMs);
  const runId = String(created?.run_id || '');
  if (!isNumericRunId(runId)) {
    const err = new Error(`${input.skillId} 未返回有效 AgentRun id`);
    (err as Error & { status?: number }).status = 502;
    throw err;
  }
  const pendingId = enqueuePendingGrowthWrite({
    userId: input.userId,
    skillId: input.skillId,
    runId,
    query: input.query ?? input.message,
    payload: input.context,
    status: 'polling',
  });
  let result: any;
  try {
    result = await pollHarnessResult(runId, created, timeoutMs);
  } catch (err) {
    updatePendingGrowthWrite(pendingId, { status: 'pending_reconcile', bumpAttempt: true, lastError: (err as Error).message });
    throw err;
  }
  if (result?.review_status === 'PASS') {
    if (input.patcher) {
      try {
        commitHarnessPass({
          userId: input.userId,
          runId,
          skillId: input.skillId,
          query: input.query ?? input.message,
          result,
          patch: input.patcher(runId, result),
          pendingId,
          traceId: result?.trace_id,
        });
      } catch (err) {
        updatePendingGrowthWrite(pendingId, {
          status: 'pending_reconcile',
          lastError: (err as Error).message,
        });
        throw err;
      }
    } else {
      updatePendingGrowthWrite(pendingId, { status: 'written', runId });
      saveRunArtifact({
        userId: input.userId,
        runId,
        traceId: result?.trace_id,
        skillId: input.skillId,
        query: input.query ?? input.message,
        reviewStatus: 'PASS',
        payload: result,
      });
    }
  } else {
    updatePendingGrowthWrite(pendingId, {
      status: String(result?.status || '') === 'waiting_for_user' ? 'waiting_input' : 'failed',
    });
  }
  return result;
}

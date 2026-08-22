import { Router, Response } from 'express';
import { authMiddleware, AuthRequest } from '../middleware/auth';
import { rateLimit } from '../middleware/rateLimit';

export const agentRouter = Router();

agentRouter.use(authMiddleware);

// 检索代理限流：同一 IP 每分钟最多 12 次检索（每次可能打外部后端+长轮询）
agentRouter.use(rateLimit({ windowMs: 60_000, max: 12, label: 'agent-chat' }));

// ============================================================================
// 检索智能体代理
// ----------------------------------------------------------------------------
// 前端契约：POST /api/agent/chat → SSE（thinking/result/summary/done/error）。
// 本路由作为 D 侧代理，把检索请求转发给 A 的 mentor-workflows 后端（非流式轮询），
// 再把 A 的事件/结果映射成本端 SSE 契约回推给前端 —— 前端零改动，符合 D 协作铁律。
//
// 当 MENTOR_AGENT_BASE_URL 未配置或 A 后端连不上时，自动回退到本地 stub 假数据，
// 保证离线演示可用。
// ============================================================================

// ---- A 后端 mentor-workflows 轮询配置（来自 Code/.env）----
const AGENT_BASE = process.env.MENTOR_AGENT_BASE_URL || '';
const AGENT_TIMEOUT = Number(process.env.MENTOR_AGENT_TIMEOUT_MS) || 180000;
const AGENT_POLL = Number(process.env.MENTOR_AGENT_POLL_MS) || 1200;

// 事件类型 → 可读的“思考中”文案（只展示关键节点，避免刷屏）
const EVENT_HINT: Record<string, string> = {
  INPUT_RECEIVED: '已收到你的需求，正在理解意图…',
  INTENT_READY: '意图已确认，正在规划检索方案…',
  PLAN_READY: '检索方案已规划，开始调用领域专家…',
  DOMAIN_ANALYSIS_STARTED: '正在分析你的研究方向领域…',
  RESEARCH_STARTED: '正在检索导师数据库，匹配研究方向与学术指标…',
  RESEARCH_DONE: '导师研究信息采集完成…',
  MATCHING_STARTED: '正在计算导师匹配度…',
  MATCHING_DONE: '匹配度计算完成…',
  REVIEW_PASSED: '检索结果通过复核…',
  COMPOSING_RESULT: '正在汇总检索结果…',
};

// ---- Mock 导师数据（A 不可用时回退）----
interface MockAdvisor {
  id: string;
  name: string;
  title: string;
  department: string;
  tags: string[];
  hIndex?: number;
  papers: number;
  matchScore: number;
  explanation: string;
}

const CV_ADVISORS: MockAdvisor[] = [
  {
    id: '1', name: '王某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['计算机视觉', '深度学习', '图像处理'],
    hIndex: 28, papers: 152, matchScore: 92,
    explanation: '查询"计算机视觉"→扩展为CV、图像处理、深度学习、目标检测\n王老师"计算机视觉"与"深度学习"语义相似度 92%\n近5年论文15篇，论文152篇 (OpenAlex)\n院系与你专业匹配 ✅',
  },
  {
    id: '2', name: '李某某', title: '副教授', department: '信息科学技术学院',
    tags: ['计算机视觉', '模式识别', '医学图像'],
    hIndex: 19, papers: 87, matchScore: 85,
    explanation: '查询"计算机视觉"→扩展为CV、图像处理、深度学习\n李老师"模式识别"与"计算机视觉"语义相关度 85%\n论文87篇',
  },
  {
    id: '3', name: '张某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['计算机视觉', '三维重建', 'SLAM'],
    hIndex: 35, papers: 203, matchScore: 78,
    explanation: '查询"计算机视觉"→扩展为CV\n张老师"三维重建"属CV子方向，语义相似度 78%\n论文203篇',
  },
];

const AI_ADVISORS: MockAdvisor[] = [
  {
    id: '4', name: '赵某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['人工智能', '机器学习', '强化学习'],
    hIndex: 42, papers: 280, matchScore: 95,
    explanation: '查询"人工智能"→扩展为AI、机器学习、深度学习、强化学习、NLP\n赵老师"机器学习"与"强化学习"语义相似度 95%\n论文280篇',
  },
  {
    id: '5', name: '孙某某', title: '教授', department: '大数据学院',
    tags: ['人工智能', '数据挖掘', '知识图谱'],
    hIndex: 31, papers: 165, matchScore: 88,
    explanation: '查询"人工智能"→扩展为AI、机器学习\n孙老师"数据挖掘"与"人工智能"语义相关度 88%\n论文165篇',
  },
  {
    id: '6', name: '周某某', title: '副教授', department: '信息科学技术学院',
    tags: ['人工智能', '自然语言处理', '大语言模型'],
    hIndex: 24, papers: 98, matchScore: 82,
    explanation: '查询"人工智能"→扩展为AI、NLP\n周老师"NLP"属AI子方向，语义相似度 82%\n论文98篇',
  },
];

const DEFAULT_ADVISORS: MockAdvisor[] = [
  {
    id: '7', name: '吴某某', title: '教授', department: '计算机科学与技术学院',
    tags: ['数据库', '大数据', '分布式系统'],
    hIndex: 36, papers: 210, matchScore: 70,
    explanation: '根据关键词综合匹配\n吴老师研究方向与查询部分相关\n论文210篇',
  },
  {
    id: '8', name: '郑某某', title: '教授', department: '数学科学学院',
    tags: ['优化理论', '机器学习', '统计学习'],
    hIndex: 29, papers: 140, matchScore: 65,
    explanation: '根据关键词综合匹配\n郑老师研究方向与查询存在交叉\n论文140篇',
  },
];

/** 根据消息关键词选择 mock 数据集 */
function pickAdvisors(message: string): MockAdvisor[] {
  const lower = message.toLowerCase();
  if (lower.includes('cv') || lower.includes('视觉') || lower.includes('图像') || lower.includes('vision')) {
    return CV_ADVISORS;
  }
  if (lower.includes('ai') || lower.includes('人工智能') || lower.includes('机器学习') || lower.includes('深度学习')) {
    return AI_ADVISORS;
  }
  return DEFAULT_ADVISORS;
}

/** 工具函数：发送 SSE 事件 */
function sse(res: Response, event: string, data: unknown): void {
  res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ============================================================================
// A 后端 mentor-workflows 轮询客户端
// ============================================================================

/**
 * 把 A 的 FinalMentorResult（candidate + match 嵌套）映射为前端 Advisor。
 * 字段映射收在 D 侧路由，A/C 输出格式零改动（协作铁律）。
 */
function mapFinalMentor(m: any, index: number): any {
  const candidate = m?.candidate ?? {};
  const match = m?.match ?? {};
  const pubList: unknown[] = Array.isArray(candidate.publications) ? candidate.publications : [];
  return {
    id: candidate.candidate_id ?? String(index + 1),
    name: candidate.mentor_name ?? '未知导师',
    title: candidate.source_metadata?.academic_title ?? '',
    department: candidate.department ?? '',
    tags: Array.isArray(candidate.research_topics) ? candidate.research_topics : [],
    papers: pubList.length,
    matchScore: Math.round(Number(match.total_score ?? 0)),
    explanation: Array.isArray(match.rationale) ? match.rationale.join('\n') : undefined,
    hIndex: undefined, // A/RAG 无真实 H 指数，Type 允许省略
  };
}

/**
 * 走 A 后端（非流式轮询）：POST 建工作流 → resume → 轮询 events/status → result。
 * 通过 onThinking 把 A 的事件以“思考中”推回，完成后返回结果。
 */
async function proxyToMentorAgent(
  message: string,
  onThinking: (text: string) => void,
  isCancelled: () => boolean = () => false,
): Promise<
  | { ok: true; advisors: any[]; summary: string }
  | { ok: false; error: string }
  | { ok: true; clarification: string[] }
> {
  const base = AGENT_BASE.replace(/\/+$/, '');
  try {
    // 1. 创建工作流（异步模式，execute_immediately=false）
    const createRes = await fetch(`${base}/api/mentor-workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, execute_immediately: false }),
      signal: AbortSignal.timeout(AGENT_TIMEOUT),
    });
    if (!createRes.ok) {
      const txt = await createRes.text().catch(() => '');
      return { ok: false, error: `创建工作流失败 (${createRes.status}): ${txt.slice(0, 200)}` };
    }
    const created: any = await createRes.json();
    const traceId: string | undefined = created?.trace_id;
    if (!traceId) return { ok: false, error: 'A 后端未返回 trace_id' };

    // 2. 触发执行（不 await，让 A 异步跑，随后轮询）
    fetch(`${base}/api/mentor-workflows/${traceId}/resume`, { method: 'POST' }).catch(() => {});

    // 3. 轮询 events/status，把新事件转成 thinking 推回
    const seen = new Set<string>();
    const deadline = Date.now() + AGENT_TIMEOUT;
    let status = 'PENDING';
    let clarification: string[] = [];

    // 客户端断开（isCancelled 返回 true）时立即停止轮询，不再空转至超时，节约资源。
    while (Date.now() < deadline && !isCancelled()) {
      await sleep(AGENT_POLL);

      // events：增量推 thinking
      try {
        const evRes = await fetch(`${base}/api/mentor-workflows/${traceId}/events`, {
          signal: AbortSignal.timeout(AGENT_POLL * 2),
        });
        if (evRes.ok) {
          const events: any[] = await evRes.json();
          for (const ev of events || []) {
            if (ev?.message_id && !seen.has(ev.message_id)) {
              seen.add(ev.message_id);
              const hint = EVENT_HINT[ev.event_type];
              if (hint) onThinking(hint);
            }
          }
        }
      } catch {
        /* 单次事件拉取失败忽略，继续轮询 */
      }

      // status：到终态跳出
      try {
        const stRes = await fetch(`${base}/api/mentor-workflows/${traceId}/status`, {
          signal: AbortSignal.timeout(AGENT_POLL * 2),
        });
        if (stRes.ok) {
          const st: any = await stRes.json();
          status = st?.status ?? status;
          if (status === 'CLARIFICATION_REQUIRED') {
            const qs: unknown = st?.clarification_request?.questions;
            clarification = Array.isArray(qs)
              ? qs.map((q) => String(q)).filter(Boolean)
              : [];
          }
          if (status === 'COMPLETED' || status === 'FAILED' || status === 'CLARIFICATION_REQUIRED') break;
        }
      } catch {
        /* 忽略 */
      }
    }

    if (status === 'CLARIFICATION_REQUIRED') {
      return { ok: true, clarification };
    }

    if (status !== 'COMPLETED') {
      return { ok: false, error: status === 'FAILED' ? 'A 后端检索失败（FAILED）' : 'A 后端检索超时' };
    }

    // 4. 取结果
    const resultRes = await fetch(`${base}/api/mentor-workflows/${traceId}/result`, {
      signal: AbortSignal.timeout(AGENT_TIMEOUT),
    });
    if (!resultRes.ok) return { ok: false, error: `获取检索结果失败 (${resultRes.status})` };

    const data: any = await resultRes.json();
    const mentors: any[] = Array.isArray(data?.mentors) ? data.mentors : [];
    const advisors = mentors.map(mapFinalMentor).filter((a: any) => a.name !== '未知导师');
    return {
      ok: true,
      advisors,
      summary: `为你找到 ${advisors.length} 位匹配导师，已按匹配度排序。`,
    };
  } catch (err: any) {
    return { ok: false, error: err?.message || '代理调用 A 后端异常' };
  }
}

// ============================================================================
// POST /api/agent/chat（SSE）
// ============================================================================
agentRouter.post('/chat', (req: AuthRequest, res: Response) => {
  const { message } = req.body ?? {};

  if (!message || typeof message !== 'string') {
    res.status(400).json({ message: '请提供 message 字段' });
    return;
  }

  // SSE headers
  res.status(200)
    .set({
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    })
    .flushHeaders();

  // 客户端断开时置标志，用于中止轮询循环
  const aborted = { cancelled: false };
  req.on('aborted', () => {
    aborted.cancelled = true;
    res.end();
  });

  const sendThinking = (text: string) => {
    if (aborted.cancelled) return;
    sse(res, 'thinking', { type: 'thinking', content: text });
  };

  const finish = (data: unknown, ok: boolean) => {
    if (aborted.cancelled) return;
    if (ok) {
      sse(res, 'done', { type: 'done' });
    } else {
      sse(res, 'error', { type: 'error', message: data });
    }
    res.end();
  };

  // ---- 主流程 ----
  (async () => {
    // 无 A 配置 → 直接走 stub
    if (!AGENT_BASE) {
      runStub(message, res, aborted);
      return;
    }

    // 尝试走 A 后端（非流式轮询）；客户端断开即停止轮询
    sendThinking('正在连接检索服务并分析你的需求…');
    const result = await proxyToMentorAgent(message, sendThinking, () => aborted.cancelled);

    if (aborted.cancelled) return;

    if (!result.ok) {
      // A 连不上/失败 → 回退 stub，并提示用的是演示数据
      sendThinking('检索服务暂不可用，已切换为演示数据。');
      runStub(message, res, aborted);
      return;
    }

    if ('clarification' in result) {
      // A 需要补充信息：把澄清问题转成可读提示回给前端，避免超时/空转。
      const questions = result.clarification.filter((q) => q.trim().length > 0);
      const content = questions.length
        ? `需要补充一点信息才能继续：\n${questions.map((q) => `· ${q}`).join('\n')}`
        : '需要补充一点信息才能继续，请换个更具体的研究方向或关键词试试。';
      sse(res, 'thinking', { type: 'thinking', content });
      sse(res, 'summary', { type: 'summary', content });
      sse(res, 'done', { type: 'done' });
      res.end();
      return;
    }

    if (result.advisors.length === 0) {
      sse(res, 'result', { type: 'result', advisors: [] });
      sse(res, 'summary', { type: 'summary', content: '未找到匹配的导师，试试换个研究方向。' });
      sse(res, 'done', { type: 'done' });
      res.end();
      return;
    }

    sse(res, 'result', { type: 'result', advisors: result.advisors });
    sse(res, 'summary', { type: 'summary', content: result.summary });
    sse(res, 'done', { type: 'done' });
    res.end();
  })().catch((err) => {
    if (aborted.cancelled) return;
    sse(res, 'error', { type: 'error', message: err?.message || '内部错误' });
    res.end();
  });
});

/**
 * 运行本地 stub 假数据（思考→结果→总结→done），模拟流式体验。
 * 供 A 不可用或未配置时回退用。
 */
function runStub(
  message: string,
  res: Response,
  aborted: { cancelled: boolean },
): void {
  const advisors = pickAdvisors(message);

  let allocated = 0;
  const at = (delay: number, fn: () => void) => {
    allocated += delay;
    setTimeout(() => {
      if (aborted.cancelled) return;
      fn();
    }, allocated);
  };

  at(500, () => sse(res, 'thinking', { type: 'thinking', content: '正在分析你的需求…' }));
  at(700, () => {
    const tags = advisors.flatMap((a) => a.tags).slice(0, 5);
    sse(res, 'thinking', { type: 'thinking', content: `已将关键词扩展为：${tags.join('、')}…` });
  });
  at(800, () => sse(res, 'thinking', { type: 'thinking', content: '正在检索导师数据库，匹配研究方向与学术指标…' }));
  at(600, () => sse(res, 'thinking', { type: 'thinking', content: '匹配度计算完成，正在汇总结果…' }));
  at(500, () => {
    const spun = advisors.map((a) => ({
      ...a,
      matchScore: a.matchScore + Math.floor(Math.random() * 5),
    }));
    sse(res, 'result', { type: 'result', advisors: spun });
  });
  at(400, () => sse(res, 'summary', { type: 'summary', content: `为你找到 ${advisors.length} 位匹配导师，已按匹配度排序（演示数据）。` }));
  at(300, () => {
    sse(res, 'done', { type: 'done' });
    res.end();
  });
}

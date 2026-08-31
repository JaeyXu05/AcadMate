/**
 * 多智能体 → 中文展示名映射。
 * sender 是后端/回退路径里的 agent 原值（如 mentor_research_agent），
 * 统一映射成中文名 + Lucide 细线图标。
 */
import type { LucideIcon } from 'lucide-react';
import {
  Brain,
  ClipboardList,
  FlaskConical,
  Compass,
  Search,
  Scale,
  SearchCheck,
  RotateCw,
  Layers,
  GitBranch,
  ArrowUpFromLine,
  Bot,
} from 'lucide-react';

const AGENT_ICON: LucideIcon = Bot;

const AGENT_MAP: Array<{ key: string; name: string; Icon: LucideIcon }> = [
  { key: 'input_understanding', name: '意图理解 Agent', Icon: Brain },
  { key: 'input', name: '意图理解 Agent', Icon: Brain },
  { key: 'intent', name: '意图理解 Agent', Icon: Brain },
  { key: 'planning', name: '计划 Agent', Icon: ClipboardList },
  { key: 'plan', name: '计划 Agent', Icon: ClipboardList },
  { key: 'domain_expert', name: '领域专家 Agent', Icon: FlaskConical },
  { key: 'retrieval_manager', name: '检索管理 Agent', Icon: Compass },
  { key: 'mentor_research', name: '导师检索 Agent', Icon: Search },
  { key: 'research', name: '导师检索 Agent', Icon: Search },
  { key: 'matching', name: '匹配计算 Agent', Icon: Scale },
  { key: 'match', name: '匹配计算 Agent', Icon: Scale },
  { key: 'evidence_review', name: '证据复核 Agent', Icon: SearchCheck },
  { key: 'review', name: '证据复核 Agent', Icon: SearchCheck },
  { key: 'retry', name: '重试控制 Agent', Icon: RotateCw },
  { key: 'result_composer', name: '结果编排 Agent', Icon: Layers },
  { key: 'compos', name: '结果编排 Agent', Icon: Layers },
  { key: 'workflow_orchestrator', name: '编排器', Icon: GitBranch },
  { key: 'api', name: '接口出口', Icon: ArrowUpFromLine },
  { key: 'intake', name: '意图理解 Agent', Icon: Brain },
  { key: 'domain', name: '领域专家 Agent', Icon: FlaskConical },
  { key: 'evaluation', name: '匹配评审 Agent', Icon: Scale },
  { key: 'composer', name: '结果编排 Agent', Icon: Layers },
];

/** 把 agent 原值（sender）映射成中文名 + Lucide 图标 */
export function agentLabel(sender?: string): { name: string; Icon: LucideIcon } {
  if (!sender) return { name: '工作流', Icon: AGENT_ICON };
  const s = sender.toLowerCase();
  for (const m of AGENT_MAP) {
    if (s.includes(m.key)) return { name: m.name, Icon: m.Icon };
  }
  return { name: sender.replace(/_/g, ' '), Icon: AGENT_ICON };
}

/** 阶段（WorkflowStage）→ 负责该阶段的 agent 展示 */
export function stageAgent(stage: string): { name: string; Icon: LucideIcon } {
  const map: Record<string, string> = {
    input_understanding: 'input_understanding_agent',
    planning: 'planning_agent',
    domain_expert: 'domain_expert_agent',
    mentor_research: 'mentor_research_agent',
    matching: 'matching_agent',
    evidence_review: 'evidence_review_agent',
    result_composer: 'result_composer_agent',
  };
  return agentLabel(map[stage] ?? '');
}

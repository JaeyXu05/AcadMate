import { useMissionStore } from '../stores/missionStore';
import { stageAgent, agentLabel } from '../utils/agentLabel';
import AgentMark from './AgentMark';

const STAGE_LABEL: Record<string, string> = {
  input_understanding: '听懂你的需求',
  planning: '制定检索计划',
  domain_expert: '锁定研究领域',
  mentor_research: '检索导师',
  matching: '计算匹配度',
  evidence_review: '核对依据',
  result_composer: '整理结果',
  completed: '已完成',
  failed: '失败',
};

const STAGE_HINT: Record<string, string> = {
  input_understanding: '读懂你输入的方向和关键词',
  planning: '安排好接下来要查哪些内容',
  domain_expert: '判断这属于哪个研究领域',
  mentor_research: '在导师库中搜索符合条件的老师',
  matching: '给每位老师打分、排序',
  evidence_review: '检查推荐依据够不够新、靠不靠谱',
  result_composer: '把结果汇总成可看的列表',
};

const STAGE_ORDER = [
  'input_understanding', 'planning', 'domain_expert', 'mentor_research',
  'matching', 'evidence_review', 'result_composer', 'completed',
];

const STEP_NAME: Record<string, string> = {
  domain_analysis: '领域分析',
  mentor_research: '检索导师',
  matching: '计算匹配度',
  evidence_review: '核对依据',
  result_composer: '整理结果',
  input_understanding: '听懂需求',
  planning: '制定计划',
};

function MissionPlanPanel() {
  const currentStage = useMissionStore((s) => s.currentStage);
  const plan = useMissionStore((s) => s.plan);
  const retryCount = useMissionStore((s) => s.retryCount);
  const events = useMissionStore((s) => s.events);
  const qualityStatus = useMissionStore((s) => s.qualityStatus);
  const reviewDecision = useMissionStore((s) => s.reviewDecision);

  const noMatch = qualityStatus === 'NO_MATCH' || qualityStatus === 'VETO'
    || reviewDecision?.status === 'NO_MATCH'
    || reviewDecision?.failed_checks?.includes('no_qualified_match');
  const currentIdx = currentStage ? STAGE_ORDER.indexOf(currentStage) : -1;
  const reviewIdx = STAGE_ORDER.indexOf('evidence_review');

  return (
    <div>
      <div className="space-y-4">
        {STAGE_ORDER.slice(0, 7).map((st, i) => {
          const failedStep = noMatch && (st === 'evidence_review' || st === 'result_composer');
          const done = failedStep ? false : (noMatch ? i < reviewIdx : currentIdx > i);
          const active = failedStep ? st === 'evidence_review' : currentIdx === i;
          const ag = stageAgent(st);
          return (
            <div key={st} className={done ? 'opacity-40' : ''}>
              <div className="flex gap-3">
                <AgentMark Icon={ag.Icon} />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-700">
                    {STAGE_LABEL[st]}
                    {active && !failedStep && (
                      <span className="ml-2 text-xs font-normal text-slate-500">正在做</span>
                    )}
                    {failedStep && (
                      <span className="ml-2 text-xs font-normal text-slate-500">无匹配</span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                    {STAGE_HINT[st]}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {retryCount > 0 && (
        <p className="mt-4 text-xs text-slate-500">已重试 {retryCount} 次（复核转折）</p>
      )}

      {plan?.steps && plan.steps.length > 0 ? (
        <ul className="mt-6 space-y-4">
          {plan.steps.map((s: any, i: number) => {
            const rawId = typeof s === 'string' ? s : s?.step_id;
            const agentName = typeof s === 'string' ? undefined : s?.agent_name;
            const stepLabel = STEP_NAME[rawId] ?? rawId ?? `step_${i + 1}`;
            const ag = agentLabel(agentName);
            return (
              <li key={rawId ?? i} className="flex gap-3">
                <AgentMark Icon={ag.Icon} />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-700">{stepLabel}</div>
                  <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{ag.name}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-6 text-xs leading-relaxed text-slate-500">
          {events.length === 0
            ? '发送检索请求后，计划与阶段将在此实时推进。'
            : '计划详情待 PLAN_READY 事件到达后展示。'}
        </p>
      )}
    </div>
  );
}

export default MissionPlanPanel;

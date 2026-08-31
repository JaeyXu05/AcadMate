import { useMissionStore } from '../../stores/missionStore';
import RuntimeTimeline from '../RuntimeTimeline';

const STAGE_ORDER = [
  'input_understanding',
  'planning',
  'domain_expert',
  'mentor_research',
  'matching',
  'evidence_review',
  'result_composer',
  'completed',
];

function ActivityTimeline() {
  const events = useMissionStore((s) => s.events);
  const running = useMissionStore((s) => s.running);
  const currentStage = useMissionStore((s) => s.currentStage);
  const stageIdx = currentStage ? STAGE_ORDER.indexOf(currentStage) : -1;
  const progressPct =
    stageIdx < 0 ? (running ? 8 : 0) : Math.round(((stageIdx + 1) / STAGE_ORDER.length) * 100);

  return (
    <section>
      <div className="mb-4 flex items-baseline gap-3">
        <span className="font-mono text-[11px] tracking-wide text-slate-400">01</span>
        <h2 className="text-sm font-semibold text-slate-800">
          运行轨迹
        </h2>
        {running && (
          <span className="text-[11px] text-slate-500">进行中</span>
        )}
      </div>
      <div className="mb-4 h-0.5 w-full overflow-hidden rounded-full bg-indigo-100">
        <div
          className="h-full bg-gradient-to-r from-purple-300 to-indigo-400 transition-all duration-500"
          style={{ width: `${progressPct}%` }}
        />
      </div>
      {events.length > 0 ? (
        <RuntimeTimeline events={events} streaming={running} />
      ) : (
        <p className="text-[13px] leading-relaxed text-slate-500">
          开始检索后，这里会按时间记下每一步。
        </p>
      )}
    </section>
  );
}

export default ActivityTimeline;

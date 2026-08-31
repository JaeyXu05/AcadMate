import { useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { useMissionStore } from '../stores/missionStore';
import { useSearchStore } from '../stores/searchStore';
import { stageAgent } from '../utils/agentLabel';
import { progressFromEvents, RUN_STRIP_STAGES } from '../utils/workflowStage';

const HOLD_MS = 4000;

function AgentRunStrip() {
  const running = useMissionStore((s) => s.running);
  const events = useMissionStore((s) => s.events);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const [holding, setHolding] = useState(false);
  const hadRun = useRef(false);

  const live = running || isStreaming;

  useEffect(() => {
    if (live) {
      hadRun.current = true;
      setHolding(false);
      return;
    }
    if (!hadRun.current || events.length === 0) return;
    setHolding(true);
    const timer = window.setTimeout(() => {
      setHolding(false);
      hadRun.current = false;
    }, HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [live, events.length]);

  if (!live && !holding) return null;

  const { activeIdx, allDone, failed } = progressFromEvents(events, live);

  return (
    <div className="relative z-10 mb-4 shrink-0 overflow-x-auto rounded-2xl border border-indigo-100 bg-white px-4 py-3">
      <ol className="flex min-w-max items-center">
        {RUN_STRIP_STAGES.map((stage, i) => {
          const done = allDone || i < activeIdx;
          const active = !allDone && activeIdx === i;
          const { name, Icon } = stageAgent(stage);
          return (
            <li key={stage} className="flex min-w-0 items-center">
              {i > 0 && (
                <span
                  aria-hidden
                  className={[
                    'mx-1 h-px w-7 shrink-0 sm:w-9',
                    done || active ? 'bg-indigo-200' : 'bg-slate-200',
                  ].join(' ')}
                />
              )}
              <div className="flex flex-col items-center gap-1.5 px-0.5">
                <span
                  className={[
                    'relative flex h-7 w-7 items-center justify-center rounded-full border',
                    active
                      ? 'border-indigo-300 bg-indigo-50 shadow-sm shadow-indigo-100'
                      : done
                        ? 'border-slate-200 bg-white'
                        : 'border-slate-200/80 bg-transparent',
                  ].join(' ')}
                >
                  {done ? (
                    <Check size={13} strokeWidth={1.5} className="text-emerald-600/70" />
                  ) : (
                    <Icon
                      size={13}
                      strokeWidth={1.5}
                      className={active ? 'text-indigo-500' : 'text-slate-400'}
                    />
                  )}
                  {active && (
                    <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-indigo-400" />
                  )}
                </span>
                <span
                  className={[
                    'whitespace-nowrap text-[11px] leading-none',
                    active
                      ? 'font-medium text-indigo-600'
                      : done
                        ? 'text-slate-600'
                        : 'text-slate-400',
                  ].join(' ')}
                >
                  {name.replace(/ Agent$/, '')}
                  {active ? ' Agent' : ''}
                </span>
                {active && (
                  <span className="text-[10px] leading-none text-indigo-400">
                    {failed ? '已中断' : '进行中'}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export default AgentRunStrip;

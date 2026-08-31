import { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Menu, PanelRight } from 'lucide-react';
import Sidebar from './Sidebar';
import MobileDrawer from './MobileDrawer';
import KnowledgeGraphWatermark from './KnowledgeGraphWatermark';
import ActivityTimeline from './ActivityTimeline';
import ReferenceSection from './ReferenceSection';
import MissionPlanPanel from '../MissionPlanPanel';
import { useMissionStore } from '../../stores/missionStore';
import { useAutoScroll } from '../../utils/useAutoScroll';

const railGlass =
  'border border-white/60 bg-white/60 shadow-xl shadow-indigo-100 backdrop-blur-2xl';

function RightRail() {
  const events = useMissionStore((state) => state.events);
  const evidenceLedger = useMissionStore((state) => state.evidenceLedger);
  const plan = useMissionStore((state) => state.plan);
  const reviewDecision = useMissionStore((state) => state.reviewDecision);
  const { scrollerRef, endRef, onScroll } = useAutoScroll([
    events,
    evidenceLedger,
    plan,
    reviewDecision,
  ]);

  return (
    <aside className={`flex h-full min-h-0 flex-col overflow-hidden rounded-2xl ${railGlass}`}>
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-5 py-6"
      >
        <ActivityTimeline />
        <ReferenceSection />
        <section className="mt-10">
          <div className="mb-4 flex items-baseline gap-3">
            <span className="font-mono text-[11px] tracking-wide text-slate-400">03</span>
            <h2 className="text-sm font-semibold text-slate-800">检索计划</h2>
          </div>
          <MissionPlanPanel />
        </section>
        <div ref={endRef} />
      </div>
    </aside>
  );
}

function Shell() {
  const location = useLocation();
  const isCloud = location.pathname.startsWith('/cloud');
  const showRightRail = location.pathname === '/search';
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-gradient-to-br from-indigo-100 via-purple-50 to-sky-100">
      {!isCloud && (
        <>
          <div className="pointer-events-none absolute -left-24 top-[-60px] h-[28rem] w-[28rem] rounded-full bg-purple-200 opacity-40 blur-3xl" />
          <div className="pointer-events-none absolute -right-16 top-10 h-[32rem] w-[32rem] rounded-full bg-indigo-200 opacity-40 blur-3xl" />
          <div className="pointer-events-none absolute bottom-[-80px] left-1/3 h-96 w-96 rounded-full bg-sky-200 opacity-40 blur-3xl" />
        </>
      )}
      <KnowledgeGraphWatermark />

      <div
        className={[
          'relative z-10 grid h-full min-h-0 p-6 md:p-8 xl:p-10',
          'gap-6 md:gap-8 xl:gap-10',
          isCloud || !showRightRail
            ? 'grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)]'
            : 'grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_320px]',
        ].join(' ')}
      >
        <div className="hidden min-h-0 lg:block">
          <Sidebar />
        </div>

        <div className="flex min-h-0 min-w-0 flex-col">
          <div className="mb-4 flex shrink-0 items-center gap-2 lg:mb-0 lg:h-0 lg:overflow-visible">
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-800 lg:hidden"
              onClick={() => setDrawerOpen(true)}
              aria-label="打开导航"
            >
              <Menu size={18} strokeWidth={1.5} className="text-indigo-500" />
            </button>
            {showRightRail && (
              <button
                type="button"
                className="ml-auto flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-800 xl:hidden"
                onClick={() => setRightOpen(true)}
                aria-label="打开运行轨迹"
              >
                <PanelRight size={18} strokeWidth={1.5} className="text-indigo-500" />
              </button>
            )}
          </div>

          {isCloud ? (
            <div className="min-h-0 flex-1 overflow-hidden rounded-2xl bg-[#030611]">
              <div className="flex h-full min-h-0 flex-col">
                <Outlet />
              </div>
            </div>
          ) : (
            <main className="relative z-10 min-h-0 flex-1 overflow-hidden rounded-2xl border border-white/60 bg-white/70 px-6 py-5 shadow-xl shadow-indigo-100 backdrop-blur-2xl">
              <Outlet />
            </main>
          )}
        </div>

        {showRightRail && (
          <div className="hidden min-h-0 xl:block">
            <RightRail />
          </div>
        )}
      </div>

      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      {showRightRail && rightOpen && (
        <div className="fixed inset-0 z-50 xl:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-stone-900/20"
            aria-label="关闭侧栏"
            onClick={() => setRightOpen(false)}
          />
          <div className="absolute bottom-4 right-4 top-4 w-[min(320px,88vw)]">
            <RightRail />
          </div>
        </div>
      )}
    </div>
  );
}

export default Shell;

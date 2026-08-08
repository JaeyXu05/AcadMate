import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api/client';
import { AppShell, type AppPage, type NavMode } from './components/AppShell';
import { PaperArchive } from './features/papers/PaperArchive';
import { PaperDetail } from './features/papers/PaperDetail';
import { ReportIndex } from './features/reports/ReportIndex';
import { ReportReader } from './features/reports/ReportReader';
import { ChatPage } from './features/chat/ChatPage';
import { MemoryPage } from './features/memory/MemoryPage';
import { SettingPage } from './features/settings/SettingPage';
import { ArxivTaskPage } from './features/tasks/ArxivTaskPage';
import type { RunRead } from './api/types';

export function App() {
  const [activePage, setActivePage] = useState<AppPage>('chat');
  const [navMode, setNavMode] = useState<NavMode>('title');
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(() => storedNumber('paper-claw:selected-thread-id'));
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(null);
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [paperMobilePane, setPaperMobilePane] = useState<'list' | 'detail'>('list');
  const [reportMobilePane, setReportMobilePane] = useState<'list' | 'detail'>('list');
  const [activeRunIdByThreadId, setActiveRunIdByThreadId] = useState<Record<number, number>>(() => {
    const storedRunId = storedNumber('paper-claw:active-run-id');
    return selectedThreadId != null && storedRunId != null ? { [selectedThreadId]: storedRunId } : {};
  });
  const [draftActiveRunId, setDraftActiveRunId] = useState<number | null>(() => (selectedThreadId == null ? storedNumber('paper-claw:active-run-id') : null));
  const [activePaperId, setActivePaperId] = useState<number | null>(null);
  const [activeRunByThreadId, setActiveRunByThreadId] = useState<Record<number, RunRead>>({});
  const [refreshToken, setRefreshToken] = useState(0);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    storeNumber('paper-claw:selected-thread-id', selectedThreadId);
  }, [selectedThreadId]);

  const activeRunId = selectedThreadId == null ? draftActiveRunId : (activeRunIdByThreadId[selectedThreadId] ?? null);
  const activeRun = selectedThreadId == null ? null : (activeRunByThreadId[selectedThreadId] ?? null);

  useEffect(() => {
    storeNumber('paper-claw:active-run-id', activeRunId);
  }, [activeRunId]);

  const requestRefresh = useCallback(() => setRefreshToken((value) => value + 1), []);
  const selectPaper = useCallback((paperId: number) => {
    setSelectedPaperId(paperId);
    setPaperMobilePane('detail');
  }, []);

  const selectReport = useCallback((reportId: number) => {
    setSelectedReportId(reportId);
    setReportMobilePane('detail');
  }, []);

  const onRunSelected = useCallback((runId: number | null, threadId?: number | null) => {
    const targetThreadId = threadId ?? selectedThreadId;
    if (targetThreadId == null) {
      setDraftActiveRunId(runId);
      return;
    }
    setActiveRunIdByThreadId((current) => {
      const next = { ...current };
      if (runId == null) {
        delete next[targetThreadId];
      } else {
        next[targetThreadId] = runId;
      }
      return next;
    });
  }, [selectedThreadId]);
  const onRunUpdated = useCallback((run: RunRead | null, threadId?: number | null) => {
    const targetThreadId = threadId ?? run?.thread_id ?? selectedThreadId;
    if (targetThreadId == null) {
      return;
    }
    setActiveRunByThreadId((current) => {
      const next = { ...current };
      if (run == null) {
        delete next[targetThreadId];
      } else {
        next[targetThreadId] = run;
      }
      return next;
    });
  }, [selectedThreadId]);

  const deleteReport = useCallback(async (reportId: number) => {
    if (!window.confirm('Delete this report permanently?')) {
      return;
    }
    try {
      await api.deleteReport(reportId);
      setSelectedReportId((current) => {
        if (current !== reportId) {
          return current;
        }
        setReportMobilePane('list');
        return null;
      });
      requestRefresh();
      setReportError(null);
    } catch (error) {
      setReportError(error instanceof Error ? error.message : 'Failed to delete report');
    }
  }, [requestRefresh]);

  const searchSessionIds = useMemo(() => {
    const ids = new Set<number>();
    for (const event of activeRun?.events ?? []) {
      const value = event.payload.search_session_id;
      if (typeof value === 'number') {
        ids.add(value);
      }
    }
    return [...ids];
  }, [activeRun]);

  const activeRunLabel = activeRunId ? `run #${activeRunId}${activeRun ? ` · ${activeRun.status}` : ''}` : undefined;
  const activePaperLabel = activePaperId ? `paper #${activePaperId} pinned` : undefined;

  const page = (() => {
    if (activePage === 'chat') {
      return (
        <ChatPage
          selectedThreadId={selectedThreadId}
          activePaperId={activePaperId}
          activeRunId={activeRunId}
          activeRun={activeRun}
          refreshToken={refreshToken}
          globalError={globalError}
          onThreadSelected={setSelectedThreadId}
          onRunSelected={onRunSelected}
          onRunUpdated={onRunUpdated}
          onRefresh={requestRefresh}
          onActivePaperSelected={setActivePaperId}
          onError={setGlobalError}
        />
      );
    }

    if (activePage === 'paper') {
      return (
        <div className={`split-page paper-page mobile-pane-${paperMobilePane}`}>
          <aside className="section-sidebar">
            <PaperArchive
              selectedPaperId={selectedPaperId}
              activePaperId={activePaperId}
              refreshToken={refreshToken}
              onSelectPaper={selectPaper}
              onSetActivePaper={setActivePaperId}
            />
          </aside>
          <main className="workspace-main">
            <button className="mobile-back-button" type="button" onClick={() => setPaperMobilePane('list')}>
              Back to papers
            </button>
            <PaperDetail
              key={selectedPaperId ?? 'empty-paper'}
              paperId={selectedPaperId}
              activeRunId={activeRunId}
              refreshToken={refreshToken}
              onSelectReport={(reportId) => {
                setSelectedReportId(reportId);
                setActivePage('report');
                setReportMobilePane('detail');
              }}
              onRefresh={requestRefresh}
            />
          </main>
        </div>
      );
    }

    if (activePage === 'report') {
      return (
        <div className={`split-page report-page mobile-pane-${reportMobilePane}`}>
          <aside className="section-sidebar">
            <ReportIndex selectedReportId={selectedReportId} refreshToken={refreshToken} errorMessage={reportError} onSelectReport={selectReport} onDeleteReport={deleteReport} />
          </aside>
          <main className="workspace-main">
            <button className="mobile-back-button" type="button" onClick={() => setReportMobilePane('list')}>
              Back to reports
            </button>
            <ReportReader
              key={selectedReportId ?? 'empty-report'}
              reportId={selectedReportId}
              onSelectPaper={(paperId) => {
                setSelectedPaperId(paperId);
                setActivePaperId(paperId);
                setActivePage('paper');
                setPaperMobilePane('detail');
              }}
              onDeleteReport={deleteReport}
            />
          </main>
        </div>
      );
    }

    if (activePage === 'memory') {
      return <MemoryPage refreshToken={refreshToken} />;
    }

    if (activePage === 'task') {
      return <ArxivTaskPage />;
    }

    return <SettingPage />;
  })();

  return (
    <AppShell
      activePage={activePage}
      navMode={navMode}
      activeRunLabel={activeRunLabel}
      activePaperLabel={activePaperLabel}
      onSelectPage={setActivePage}
      onToggleNavMode={() => setNavMode((value) => (value === 'title' ? 'icon' : 'title'))}
    >
      {page}
    </AppShell>
  );
}

function storedNumber(key: string): number | null {
  const raw = window.localStorage.getItem(key);
  if (raw == null) {
    return null;
  }
  const value = Number(raw);
  return Number.isInteger(value) && value > 0 ? value : null;
}

function storeNumber(key: string, value: number | null): void {
  if (value == null) {
    window.localStorage.removeItem(key);
    return;
  }
  window.localStorage.setItem(key, String(value));
}

export { api };

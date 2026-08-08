import { FormEvent, useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { api } from '../../api/client';
import type {
  ArxivTaskHarvestJobRead,
  ArxivTaskPaperRead,
  ArxivTaskQueryWindowRead,
  ArxivTaskSubscriptionRead,
  ArxivTaskSubscriptionTestPaperRead,
  ArxivTaskSubscriptionTestRead,
} from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';
import { usePolling } from '../../hooks/usePolling';
import { localTimeToUtcTime, utcTimeToLocalTime } from './taskTime';
import { windowRerunActionLabel } from './windowActions';
import { buildWindowTimeline, type WindowTimelineSegment } from './windowTimeline';

const runningStatuses = new Set(['running', 'pending', 'stopping']);
const PAPER_PAGE_SIZE = 20;

type WindowRangeSelection = {
  key: string;
  label: string;
  status: string;
  start: string;
  end: string;
  fetchedCount: number;
  windowIds: number[];
};

type SubscriptionDraft = {
  id: number | null;
  name: string;
  query: string;
  description: string;
  enabled: boolean;
  originalQuery: string;
};

const emptyDraft: SubscriptionDraft = {
  id: null,
  name: '',
  query: '',
  description: '',
  enabled: true,
  originalQuery: '',
};

export function ArxivTaskPage() {
  const loader = useCallback(() => api.getArxivTaskStatus(), []);
  const { data: status, loading, error, reload } = useAsyncResource(loader, []);
  const [actionError, setActionError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [dailyEnabled, setDailyEnabled] = useState(true);
  const [runTime, setRunTime] = useState('08:00');
  const [selectedSubscriptionId, setSelectedSubscriptionId] = useState<number | null>(null);
  const [historySubscriptionIds, setHistorySubscriptionIds] = useState<number[]>([]);
  const [historyStart, setHistoryStart] = useState(() => defaultDatetimeLocal(-7));
  const [historyEnd, setHistoryEnd] = useState(() => defaultDatetimeLocal(0));
  const [draft, setDraft] = useState<SubscriptionDraft>(emptyDraft);
  const [modalOpen, setModalOpen] = useState(false);
  const [testResult, setTestResult] = useState<ArxivTaskSubscriptionTestRead | null>(null);
  const [detailWindows, setDetailWindows] = useState<ArxivTaskQueryWindowRead[]>([]);
  const [detailPapers, setDetailPapers] = useState<ArxivTaskPaperRead[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [paperLoading, setPaperLoading] = useState(false);
  const [paperOffset, setPaperOffset] = useState(0);
  const [hasMorePapers, setHasMorePapers] = useState(false);
  const [selectedWindowRange, setSelectedWindowRange] = useState<WindowRangeSelection | null>(null);

  useEffect(() => {
    if (!status) {
      return;
    }
    setDailyEnabled(status.daily_config.enabled);
    setRunTime(utcTimeToLocalTime(status.daily_config.run_time));
    const fallbackId = status.coverage_subscription_ids[0] ?? status.enabled_subscription_ids[0] ?? status.subscriptions[0]?.id ?? null;
    setSelectedSubscriptionId((current) => (current != null && status.subscriptions.some((subscription) => subscription.id === current) ? current : fallbackId));
    setHistorySubscriptionIds((current) => {
      const valid = current.filter((id) => status.subscriptions.some((subscription) => subscription.id === id));
      return valid.length ? valid : fallbackId == null ? [] : [fallbackId];
    });
  }, [status]);

  const shouldPoll = Boolean(status?.active_job && runningStatuses.has(status.active_job.status));
  usePolling(reload, 2500, shouldPoll);

  const subscriptionById = useMemo(() => new Map((status?.subscriptions ?? []).map((subscription) => [subscription.id, subscription])), [status?.subscriptions]);
  const selectedSubscription = selectedSubscriptionId == null ? null : subscriptionById.get(selectedSubscriptionId) ?? null;
  const historyJobs = useMemo(() => (status?.recent_jobs ?? []).filter((job) => job.kind === 'history'), [status?.recent_jobs]);
  const selectedHistoryJobs = useMemo(() => {
    if (selectedSubscriptionId == null) {
      return historyJobs;
    }
    return historyJobs.filter((job) => job.subscription_ids.includes(selectedSubscriptionId));
  }, [historyJobs, selectedSubscriptionId]);
  const queryNeedsTest = draft.query.trim().length > 0 && (draft.id == null || draft.query !== draft.originalQuery);
  const hasCurrentQueryTest = Boolean(testResult && testResult.query === draft.query);
  const runTimeUtc = localTimeToUtcTime(runTime);

  useEffect(() => {
    setSelectedWindowRange(null);
  }, [selectedSubscriptionId]);

  useEffect(() => {
    if (selectedSubscriptionId == null) {
      setDetailWindows([]);
      return;
    }
    let active = true;
    setDetailLoading(true);
    api.listArxivTaskWindows(selectedSubscriptionId, 100)
      .then((windows) => {
        if (active) {
          setDetailWindows(windows);
        }
      })
      .catch((caught) => {
        if (active) {
          setActionError(caught instanceof Error ? caught.message : 'Failed to load subscription windows');
        }
      })
      .finally(() => {
        if (active) {
          setDetailLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedSubscriptionId, status]);

  useEffect(() => {
    if (selectedSubscriptionId == null) {
      setDetailPapers([]);
      setPaperOffset(0);
      setHasMorePapers(false);
      return;
    }
    let active = true;
    setPaperLoading(true);
    api.listArxivTaskPapers(selectedSubscriptionId, PAPER_PAGE_SIZE, 0, selectedWindowRange?.start, selectedWindowRange?.end)
      .then((papers) => {
        if (!active) {
          return;
        }
        setDetailPapers(papers);
        setPaperOffset(papers.length);
        setHasMorePapers(papers.length === PAPER_PAGE_SIZE);
      })
      .catch((caught) => {
        if (active) {
          setActionError(caught instanceof Error ? caught.message : 'Failed to load subscription papers');
        }
      })
      .finally(() => {
        if (active) {
          setPaperLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedSubscriptionId, selectedWindowRange]);

  const runAction = async (action: () => Promise<unknown>) => {
    setActionError(null);
    setSaving(true);
    try {
      await action();
      reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Task action failed');
    } finally {
      setSaving(false);
    }
  };

  const saveDailyConfig = () => runAction(() => api.updateArxivTaskDailyConfig({ enabled: dailyEnabled, run_time: runTimeUtc }));
  const runDailyNow = () => runAction(() => api.runArxivTaskDailyNow());

  const closeModal = () => {
    setModalOpen(false);
    setDraft(emptyDraft);
    setTestResult(null);
    setActionError(null);
  };

  const openNewSubscription = () => {
    setDraft(emptyDraft);
    setTestResult(null);
    setActionError(null);
    setModalOpen(true);
  };

  const openEditSubscription = (subscription: ArxivTaskSubscriptionRead) => {
    setDraft({
      id: subscription.id,
      name: subscription.name,
      query: subscription.query,
      description: subscription.description ?? '',
      enabled: subscription.enabled,
      originalQuery: subscription.query,
    });
    setTestResult(null);
    setActionError(null);
    setModalOpen(true);
  };

  const updateDraft = (patch: Partial<SubscriptionDraft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    if (patch.query !== undefined) {
      setTestResult(null);
    }
  };

  const testQuery = async () => {
    if (!draft.query.trim()) {
      setActionError('Enter an arXiv advanced query before testing.');
      return;
    }
    setActionError(null);
    setTesting(true);
    try {
      const result = await api.testArxivTaskSubscriptionQuery({ query: draft.query, max_results: 5 });
      setTestResult(result);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Query test failed');
      setTestResult(null);
    } finally {
      setTesting(false);
    }
  };

  const saveSubscription = (event: FormEvent) => {
    event.preventDefault();
    if (!draft.name.trim()) {
      setActionError('Subscription name is required.');
      return;
    }
    if (!draft.query.trim()) {
      setActionError('arXiv query is required.');
      return;
    }
    if (queryNeedsTest && !hasCurrentQueryTest) {
      setActionError('Test this query and review the preview before saving.');
      return;
    }
    const request = {
      name: draft.name.trim(),
      query: draft.query,
      description: draft.description.trim() || null,
      enabled: draft.enabled,
    };
    runAction(async () => {
      const saved = draft.id == null
        ? await api.createArxivTaskSubscription(request)
        : await api.updateArxivTaskSubscription(draft.id, request);
      setSelectedSubscriptionId(saved.id);
      closeModal();
    });
  };

  const toggleSubscriptionEnabled = (subscription: ArxivTaskSubscriptionRead) => {
    return runAction(() => api.updateArxivTaskSubscription(subscription.id, {
      name: subscription.name,
      query: subscription.query,
      description: subscription.description,
      enabled: !subscription.enabled,
    }));
  };

  const deleteSubscription = (subscription: ArxivTaskSubscriptionRead) => {
    if (!window.confirm(`Delete subscription "${subscription.name}"? Harvested links and windows for it will be removed.`)) {
      return;
    }
    return runAction(async () => {
      await api.deleteArxivTaskSubscription(subscription.id);
      if (selectedSubscriptionId === subscription.id) {
        setSelectedSubscriptionId(null);
      }
    });
  };

  const toggleHistorySubscription = (subscriptionId: number) => {
    setHistorySubscriptionIds((current) => (current.includes(subscriptionId) ? current.filter((value) => value !== subscriptionId) : [...current, subscriptionId].sort((left, right) => left - right)));
  };

  const createHistoryJob = (event: FormEvent) => {
    event.preventDefault();
    if (!historySubscriptionIds.length) {
      setActionError('Select at least one arXiv subscription for history backfill.');
      return;
    }
    runAction(() => api.createArxivTaskHistoryJob({ subscription_ids: historySubscriptionIds, start_time: toIso(historyStart), end_time: toIso(historyEnd) }));
  };

  const jobAction = (job: ArxivTaskHarvestJobRead, action: 'start' | 'pause' | 'stop') => {
    if (action === 'start') {
      return runAction(() => api.startArxivTaskHistoryJob(job.id));
    }
    if (action === 'pause') {
      return runAction(() => api.pauseArxivTaskHistoryJob(job.id));
    }
    return runAction(() => api.stopArxivTaskHistoryJob(job.id));
  };

  const loadMorePapers = async () => {
    if (selectedSubscriptionId == null || paperLoading) {
      return;
    }
    setActionError(null);
    setPaperLoading(true);
    try {
      const papers = await api.listArxivTaskPapers(selectedSubscriptionId, PAPER_PAGE_SIZE, paperOffset, selectedWindowRange?.start, selectedWindowRange?.end);
      setDetailPapers((current) => [...current, ...papers]);
      setPaperOffset((current) => current + papers.length);
      setHasMorePapers(papers.length === PAPER_PAGE_SIZE);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Failed to load more papers');
    } finally {
      setPaperLoading(false);
    }
  };

  const retryWindow = (window: ArxivTaskQueryWindowRead) => {
    runAction(async () => {
      const job = await api.createArxivTaskHistoryJob({ subscription_ids: [window.subscription_id], start_time: window.window_start, end_time: window.window_end });
      await api.startArxivTaskHistoryJob(job.id);
    });
  };

  return (
    <main className="task-page task-workspace">
      <header className="workspace-header task-hero">
        <div className="task-hero__intro">
          <p className="eyebrow">Task · arXiv</p>
          <h1>Metadata harvest console</h1>
          <p>Run raw arXiv advanced-query subscriptions through a serialized harvest queue.</p>
        </div>
        {status && (
          <div className="task-hero__dashboard">
            <section className="task-hero-card task-hero-card--overview">
              <div className="task-hero-card__header">
                <p className="eyebrow">Overview</p>
                <h2>Queue state</h2>
              </div>
              <div className="task-hero__meters">
                <Metric label="enabled subscriptions" value={status.enabled_subscription_ids.length} />
                <Metric label="task papers" value={status.total_papers} />
                <Metric label="covered subscriptions" value={status.coverage_subscription_ids.length} />
              </div>
              <dl className="task-facts">
                <Fact label="active job" value={status.active_job ? `#${status.active_job.id} · ${status.active_job.kind} · ${status.active_job.status}` : 'none'} />
                <Fact label="last daily started" value={formatDateTime(status.daily_config.last_started_at)} />
                <Fact label="last daily finished" value={formatDateTime(status.daily_config.last_finished_at)} />
              </dl>
            </section>

            <section className="task-hero-card task-hero-card--daily">
              <div className="task-hero-card__header">
                <p className="eyebrow">Daily</p>
                <h2>Incremental run</h2>
              </div>
              <div className="task-toggle-row">
                <label className="task-check-row">
                  <input type="checkbox" checked={dailyEnabled} onChange={(event) => setDailyEnabled(event.target.checked)} />
                  <span>Enable scheduler</span>
                </label>
                <label>
                  Run time
                  <input type="time" value={runTime} onChange={(event) => setRunTime(event.target.value)} />
                  <span className="meta-row">Browser timezone · saved as {runTimeUtc} UTC</span>
                </label>
              </div>
              <div className="button-row">
                <button className="secondary-button" type="button" disabled={saving} onClick={saveDailyConfig}>Save schedule</button>
                <button className="primary-button" type="button" disabled={saving} onClick={runDailyNow}>Run daily now</button>
              </div>
            </section>
          </div>
        )}
      </header>

      <ErrorBanner message={error} />
      <ErrorBanner message={actionError} />
      {loading && <LoadingBlock label="Loading arXiv task state" />}
      {!status && !loading && <EmptyState title="No task state" body="Run migrations and reload the backend to initialize arXiv task tables." />}

      {status && (
        <>
          <div className="task-main-grid">
            <section className="panel task-subscription-list-panel">
              <div className="panel-header task-panel-header-row">
                <div>
                  <p className="eyebrow">Subscriptions</p>
                  <h2>Advanced queries</h2>
                </div>
                <button className="primary-button" type="button" disabled={saving} onClick={openNewSubscription}>New subscription</button>
              </div>
              <div className="panel-body">
                <SubscriptionList
                  subscriptions={status.subscriptions}
                  activeId={selectedSubscriptionId}
                  onSelect={setSelectedSubscriptionId}
                />
              </div>
            </section>

            <section className="panel task-detail-panel">
              <div className="panel-header task-panel-header-row">
                <div>
                  <p className="eyebrow">Detail</p>
                  <h2>{selectedSubscription?.name ?? 'No subscription selected'}</h2>
                </div>
                {selectedSubscription && (
                  <div className="button-row">
                    <button className="secondary-button" type="button" disabled={saving} onClick={() => openEditSubscription(selectedSubscription)}>Edit</button>
                    <button className="secondary-button" type="button" disabled={saving} onClick={() => toggleSubscriptionEnabled(selectedSubscription)}>{selectedSubscription.enabled ? 'Disable' : 'Enable'}</button>
                    <button className="danger-button" type="button" disabled={saving} onClick={() => deleteSubscription(selectedSubscription)}>Delete</button>
                  </div>
                )}
              </div>
              <div className="panel-body stack">
                {selectedSubscription ? (
                  <SubscriptionDetail
                    subscription={selectedSubscription}
                    windows={detailWindows}
                    papers={detailPapers}
                    loading={detailLoading}
                    paperLoading={paperLoading}
                    hasMorePapers={hasMorePapers}
                    selectedWindowRange={selectedWindowRange}
                    historySubscriptionIds={historySubscriptionIds}
                    subscriptions={status.subscriptions}
                    historyStart={historyStart}
                    historyEnd={historyEnd}
                    historyJobs={selectedHistoryJobs}
                    subscriptionById={subscriptionById}
                    saving={saving}
                    onToggleHistorySubscription={toggleHistorySubscription}
                    onHistoryStartChange={setHistoryStart}
                    onHistoryEndChange={setHistoryEnd}
                    onCreateHistoryJob={createHistoryJob}
                    onJobAction={jobAction}
                    onSelectWindowRange={setSelectedWindowRange}
                    onClearWindowRange={() => setSelectedWindowRange(null)}
                    onLoadMorePapers={loadMorePapers}
                    onRetryWindow={retryWindow}
                  />
                ) : (
                  <EmptyState title="No subscription selected" body="Create or select a subscription to inspect its query, windows, papers, and backfill jobs." />
                )}
              </div>
            </section>
          </div>

          {modalOpen && (
            <SubscriptionModal
              draft={draft}
              saving={saving}
              testing={testing}
              queryNeedsTest={queryNeedsTest}
              hasCurrentQueryTest={hasCurrentQueryTest}
              testResult={testResult}
              onClose={closeModal}
              onChange={updateDraft}
              onTest={testQuery}
              onSubmit={saveSubscription}
            />
          )}
        </>
      )}
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="task-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function SubscriptionList({ subscriptions, activeId, onSelect }: { subscriptions: ArxivTaskSubscriptionRead[]; activeId: number | null; onSelect: (subscriptionId: number) => void }) {
  if (!subscriptions.length) {
    return <EmptyState title="No subscriptions" body="Create a subscription from an arXiv advanced query to start harvesting." />;
  }
  return (
    <div className="task-subscription-list">
      {subscriptions.map((subscription) => (
        <button key={subscription.id} type="button" className={`task-subscription-card ${activeId === subscription.id ? 'is-selected' : ''}`} onClick={() => onSelect(subscription.id)}>
          <span className="meta-row">
            <StatusBadge status={subscription.enabled ? 'enabled' : 'disabled'} />
            <span>#{subscription.id}</span>
            <span>{formatDateTime(subscription.last_refreshed_at)}</span>
          </span>
          <strong>{subscription.name}</strong>
          {subscription.description && <span className="task-subscription-card__description">{subscription.description}</span>}
          <code>{subscription.query}</code>
        </button>
      ))}
    </div>
  );
}

function SubscriptionDetail({
  windows,
  papers,
  loading,
  paperLoading,
  hasMorePapers,
  selectedWindowRange,
  historySubscriptionIds,
  subscriptions,
  historyStart,
  historyEnd,
  historyJobs,
  subscriptionById,
  saving,
  onToggleHistorySubscription,
  onHistoryStartChange,
  onHistoryEndChange,
  onCreateHistoryJob,
  onJobAction,
  onSelectWindowRange,
  onClearWindowRange,
  onLoadMorePapers,
  onRetryWindow,
}: {
  subscription: ArxivTaskSubscriptionRead;
  windows: ArxivTaskQueryWindowRead[];
  papers: ArxivTaskPaperRead[];
  loading: boolean;
  paperLoading: boolean;
  hasMorePapers: boolean;
  selectedWindowRange: WindowRangeSelection | null;
  historySubscriptionIds: number[];
  subscriptions: ArxivTaskSubscriptionRead[];
  historyStart: string;
  historyEnd: string;
  historyJobs: ArxivTaskHarvestJobRead[];
  subscriptionById: Map<number, ArxivTaskSubscriptionRead>;
  saving: boolean;
  onToggleHistorySubscription: (subscriptionId: number) => void;
  onHistoryStartChange: (value: string) => void;
  onHistoryEndChange: (value: string) => void;
  onCreateHistoryJob: (event: FormEvent) => void;
  onJobAction: (job: ArxivTaskHarvestJobRead, action: 'start' | 'pause' | 'stop') => void;
  onSelectWindowRange: (range: WindowRangeSelection) => void;
  onClearWindowRange: () => void;
  onLoadMorePapers: () => void;
  onRetryWindow: (window: ArxivTaskQueryWindowRead) => void;
}) {
  return (
    <>
      <div className="task-detail-stack">
        <section className="task-detail-card">
          <div className="section-heading-row">
            <h3>Retrieved windows</h3>
            {loading && <span>loading...</span>}
          </div>
          {windows.length ? (
            <WindowList
              windows={windows}
              selectedRangeKey={selectedWindowRange?.key ?? null}
              saving={saving}
              onSelectRange={onSelectWindowRange}
              onRetryWindow={onRetryWindow}
            />
          ) : <EmptyState title="No windows" body="Run daily or create a backfill job for this subscription." />}
        </section>

        <section className="task-detail-card task-papers-card">
          <div className="section-heading-row">
            <div>
              <h3>Papers</h3>
              <p className="task-section-note">{selectedWindowRange ? `${selectedWindowRange.label} · ${selectedWindowRange.fetchedCount} fetched` : 'All harvested papers for this subscription'}</p>
            </div>
            <div className="button-row">
              {selectedWindowRange && <button className="secondary-button" type="button" onClick={onClearWindowRange}>Clear filter</button>}
              {paperLoading && <span>loading...</span>}
            </div>
          </div>
          {selectedWindowRange?.status === 'failed' && <p className="task-error-text">This window failed. Retry it to harvest papers for the same time range.</p>}
          <div className="task-papers-scroll">
            {papers.length ? <PaperList papers={papers} /> : <EmptyState title="No papers" body={selectedWindowRange ? "No harvested metadata is available in this selected time range." : "Harvested metadata matching this subscription will appear here."} />}
          </div>
          {hasMorePapers && <button className="secondary-button" type="button" disabled={paperLoading} onClick={onLoadMorePapers}>Load more papers</button>}
        </section>
      </div>

      <details className="task-detail-card task-history-card">
        <summary className="section-heading-row">
          <h3>History backfill</h3>
          <span>{historySubscriptionIds.length} selected</span>
        </summary>
        <form className="task-history-form" onSubmit={onCreateHistoryJob}>
          <SubscriptionPicker subscriptions={subscriptions} selectedIds={historySubscriptionIds} onToggle={onToggleHistorySubscription} />
          <label>
            Start time
            <input type="datetime-local" value={historyStart} onChange={(event) => onHistoryStartChange(event.target.value)} />
          </label>
          <label>
            End time
            <input type="datetime-local" value={historyEnd} onChange={(event) => onHistoryEndChange(event.target.value)} />
          </label>
          <button className="primary-button" type="submit" disabled={saving}>Create history job</button>
        </form>
        <JobList jobs={historyJobs.slice(0, 6)} emptyTitle="No history jobs" subscriptionById={subscriptionById} onJobAction={onJobAction} />
      </details>
    </>
  );
}

function SubscriptionModal({
  draft,
  saving,
  testing,
  queryNeedsTest,
  hasCurrentQueryTest,
  testResult,
  onClose,
  onChange,
  onTest,
  onSubmit,
}: {
  draft: SubscriptionDraft;
  saving: boolean;
  testing: boolean;
  queryNeedsTest: boolean;
  hasCurrentQueryTest: boolean;
  testResult: ArxivTaskSubscriptionTestRead | null;
  onClose: () => void;
  onChange: (patch: Partial<SubscriptionDraft>) => void;
  onTest: () => void;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <div className="task-modal-backdrop" role="presentation">
      <section className="task-modal" role="dialog" aria-modal="true" aria-labelledby="task-subscription-modal-title">
        <div className="panel-header task-panel-header-row">
          <div>
            <p className="eyebrow">Subscription</p>
            <h2 id="task-subscription-modal-title">{draft.id == null ? 'New subscription' : 'Edit subscription'}</h2>
          </div>
          <button className="secondary-button" type="button" disabled={saving || testing} onClick={onClose}>Close</button>
        </div>
        <form className="task-modal-body" onSubmit={onSubmit}>
          <div className="task-subscription-form">
            <label>
              Name
              <input value={draft.name} onChange={(event) => onChange({ name: event.target.value })} placeholder="LLM agents" />
            </label>
            <label>
              Query
              <textarea value={draft.query} onChange={(event) => onChange({ query: event.target.value })} placeholder="cat:cs.AI AND (ti:agent OR abs:agent)" rows={6} />
            </label>
            <label>
              Description
              <textarea value={draft.description} onChange={(event) => onChange({ description: event.target.value })} rows={3} />
            </label>
            <label className="task-check-row">
              <input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ enabled: event.target.checked })} />
              <span>Enabled for daily runs</span>
            </label>
            <div className="button-row">
              <button className="secondary-button" type="button" disabled={saving || testing || !draft.query.trim()} onClick={onTest}>Test query</button>
              <button className="primary-button" type="submit" disabled={saving || testing || (queryNeedsTest && !hasCurrentQueryTest)}>
                {draft.id == null ? 'Save subscription' : 'Update subscription'}
              </button>
            </div>
          </div>

          <div className="task-query-preview">
            <div className="section-heading-row">
              <h3>Query preview</h3>
              {testing && <span>testing...</span>}
              {testResult && <span>{testResult.total_results} total</span>}
            </div>
            {testResult ? <QueryPreview result={testResult} /> : <EmptyState title="No preview" body="Test the query before saving a new or changed subscription." />}
          </div>
        </form>
      </section>
    </div>
  );
}

function WindowList({ windows, selectedRangeKey, saving, onSelectRange, onRetryWindow }: { windows: ArxivTaskQueryWindowRead[]; selectedRangeKey: string | null; saving: boolean; onSelectRange: (range: WindowRangeSelection) => void; onRetryWindow: (window: ArxivTaskQueryWindowRead) => void }) {
  const timeline = buildWindowTimeline(windows);
  return (
    <div className="task-window-console">
      <div className="task-window-summary">
        <Metric label="windows" value={timeline.summary.totalWindows} />
        <Metric label="coverage runs" value={timeline.summary.successSegmentCount} />
        <Metric label="issues" value={timeline.summary.issueCount} />
      </div>
      <div className="task-window-range">
        <span>{formatDateTime(timeline.summary.coverageStart)}</span>
        <span>{formatDateTime(timeline.summary.coverageEnd)}</span>
      </div>
      <div className="task-window-timeline" aria-label="Retrieved window coverage timeline">
        {timeline.segments.map((segment) => (
          <WindowSegment key={segment.key} segment={segment} selected={selectedRangeKey === segment.key} onSelect={onSelectRange} />
        ))}
      </div>
      <div className="task-window-detail-list">
        {timeline.details.map((window) => {
          const range = rangeFromWindow(window);
          const actionLabel = windowRerunActionLabel(window.status);
          return (
            <article key={window.id} className={`task-window-detail-row task-window-detail-row--${window.status} ${selectedRangeKey === range.key ? 'is-selected' : ''}`}>
              <button className="task-window-detail-main" type="button" onClick={() => onSelectRange(range)}>
                <span className="meta-row">
                  <StatusBadge status={window.status} />
                  <span>{window.kind}</span>
                  <span>{formatDateTime(window.window_start)} → {formatDateTime(window.window_end)}</span>
                </span>
                <span className="meta-row">
                  <span>{window.fetched_count} fetched</span>
                  <span>{window.inserted_count} new</span>
                  <span>{window.updated_count} updated</span>
                  {window.total_results != null && <span>{window.total_results} total</span>}
                  {window.warning_code && <span>{window.warning_code}</span>}
                </span>
                {(window.error_message || window.warning_code) && <span className="task-error-text">{window.error_message ?? window.warning_code}</span>}
              </button>
              {actionLabel && <button className={window.status === 'failed' ? 'danger-button' : 'secondary-button'} type="button" disabled={saving} onClick={() => onRetryWindow(window)}>{actionLabel}</button>}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function WindowSegment({ segment, selected, onSelect }: { segment: WindowTimelineSegment; selected: boolean; onSelect: (range: WindowRangeSelection) => void }) {
  return (
    <button
      type="button"
      className={`task-window-segment task-window-segment--${segment.kind} task-window-segment--${segment.status} ${selected ? 'is-selected' : ''}`}
      style={{ '--window-width': `${segment.widthPercent}%`, '--window-intensity': String(segment.intensity) } as CSSProperties}
      title={`${formatDateTime(segment.start)} → ${formatDateTime(segment.end)} · ${segment.status} · ${segment.fetchedCount} fetched`}
      onClick={() => onSelect(rangeFromSegment(segment))}
    >
      <span>{segment.kind === 'gap' ? 'gap' : segment.windowIds.length}</span>
    </button>
  );
}

function rangeFromSegment(segment: WindowTimelineSegment): WindowRangeSelection {
  return {
    key: segment.key,
    label: segment.kind === 'gap' ? `${formatDateTime(segment.start)} gap` : `${formatDateTime(segment.start)} → ${formatDateTime(segment.end)}`,
    status: segment.status,
    start: segment.start,
    end: segment.end,
    fetchedCount: segment.fetchedCount,
    windowIds: segment.windowIds,
  };
}

function rangeFromWindow(window: ArxivTaskQueryWindowRead): WindowRangeSelection {
  return {
    key: `window-${window.id}`,
    label: `${formatDateTime(window.window_start)} → ${formatDateTime(window.window_end)}`,
    status: window.status,
    start: window.window_start,
    end: window.window_end,
    fetchedCount: window.fetched_count,
    windowIds: [window.id],
  };
}

function PaperList({ papers }: { papers: ArxivTaskPaperRead[] }) {
  return (
    <div className="task-paper-list">
      {papers.map((paper) => (
        <article key={paper.id} className="task-paper-card">
          <div className="meta-row">
            <span>{paper.arxiv_id}</span>
            {paper.primary_category && <span>{paper.primary_category}</span>}
            <span>{formatDate(paper.published_at)}</span>
          </div>
          <h3>{paper.title}</h3>
          <p>{paper.abstract || 'No abstract available.'}</p>
          <div className="meta-row">
            <span>{stringifyAuthors(paper.authors).slice(0, 4).join(', ')}</span>
            {paper.landing_page_url && <a href={paper.landing_page_url} target="_blank" rel="noreferrer">arXiv</a>}
            {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer">pdf</a>}
          </div>
        </article>
      ))}
    </div>
  );
}

function SubscriptionPicker({ subscriptions, selectedIds, onToggle }: { subscriptions: ArxivTaskSubscriptionRead[]; selectedIds: number[]; onToggle: (subscriptionId: number) => void }) {
  if (!subscriptions.length) {
    return <EmptyState title="No subscriptions" body="Create a subscription before backfilling history." />;
  }
  return (
    <div className="task-chip-grid">
      {subscriptions.map((subscription) => (
        <label key={subscription.id} className={`task-subscription-chip ${selectedIds.includes(subscription.id) ? 'is-selected' : ''}`}>
          <input type="checkbox" checked={selectedIds.includes(subscription.id)} onChange={() => onToggle(subscription.id)} />
          <span>{subscription.name}</span>
        </label>
      ))}
    </div>
  );
}

function QueryPreview({ result }: { result: ArxivTaskSubscriptionTestRead }) {
  if (!result.papers.length) {
    return <EmptyState title="No results" body="The query is valid but returned no preview papers." />;
  }
  return (
    <div className="task-preview-list">
      {result.papers.map((paper) => <PreviewPaper key={paper.arxiv_id} paper={paper} />)}
    </div>
  );
}

function PreviewPaper({ paper }: { paper: ArxivTaskSubscriptionTestPaperRead }) {
  return (
    <article className="task-preview-card">
      <div className="meta-row">
        <span>{paper.arxiv_id}</span>
        {paper.primary_category && <span>{paper.primary_category}</span>}
        <span>{formatDate(paper.published_at)}</span>
      </div>
      <h4>{paper.title}</h4>
      <p>{paper.abstract || 'No abstract available.'}</p>
      <div className="meta-row">
        <span>{paper.authors.slice(0, 3).join(', ')}</span>
        {paper.landing_page_url && <a href={paper.landing_page_url} target="_blank" rel="noreferrer">arXiv</a>}
      </div>
    </article>
  );
}

function JobList({ jobs, emptyTitle, subscriptionById, onJobAction, compact = false }: { jobs: ArxivTaskHarvestJobRead[]; emptyTitle: string; subscriptionById: Map<number, ArxivTaskSubscriptionRead>; onJobAction?: (job: ArxivTaskHarvestJobRead, action: 'start' | 'pause' | 'stop') => void; compact?: boolean }) {
  if (!jobs.length) {
    return <EmptyState title={emptyTitle} body="The scheduler records each harvest attempt here." />;
  }
  return (
    <div className={compact ? 'timeline task-compact-timeline' : 'timeline'}>
      {jobs.map((job) => (
        <div key={job.id} className="timeline-event">
          <div className="meta-row">
            <StatusBadge status={job.status} />
            <span>#{job.id}</span>
            <span>{formatDateTime(job.started_at || job.created_at)}</span>
          </div>
          <div className="meta-row">
            <span>{jobSubscriptionNames(job, subscriptionById)}</span>
            <span>{statsLabel(job.stats)}</span>
          </div>
          {onJobAction && (
            <div className="button-row">
              <button className="secondary-button" type="button" disabled={['running', 'stopped', 'succeeded'].includes(job.status)} onClick={() => onJobAction(job, 'start')}>Start</button>
              <button className="secondary-button" type="button" disabled={job.status !== 'running'} onClick={() => onJobAction(job, 'pause')}>Pause</button>
              <button className="danger-button" type="button" disabled={['stopped', 'succeeded'].includes(job.status)} onClick={() => onJobAction(job, 'stop')}>Stop</button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function jobSubscriptionNames(job: ArxivTaskHarvestJobRead, subscriptionById: Map<number, ArxivTaskSubscriptionRead>): string {
  const names = job.subscription_ids.map((id) => subscriptionById.get(id)?.name ?? `#${id}`);
  return names.join(', ') || 'no subscriptions';
}

function defaultDatetimeLocal(dayOffset: number): string {
  const date = new Date();
  date.setDate(date.getDate() + dayOffset);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function toIso(value: string): string {
  return new Date(value).toISOString();
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return 'none';
  }
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function formatDate(value: string | null): string {
  if (!value) {
    return 'unknown date';
  }
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: '2-digit' }).format(new Date(value));
}

function statsLabel(stats: Record<string, number>): string {
  const fetched = stats.fetched_count ?? 0;
  const inserted = stats.inserted_count ?? 0;
  const updated = stats.updated_count ?? 0;
  return `${fetched} fetched · ${inserted} new · ${updated} updated`;
}

function stringifyAuthors(authors: unknown[]): string[] {
  return authors.map((author) => {
    if (typeof author === 'string') {
      return author;
    }
    if (author && typeof author === 'object' && 'name' in author && typeof author.name === 'string') {
      return author.name;
    }
    return String(author);
  });
}

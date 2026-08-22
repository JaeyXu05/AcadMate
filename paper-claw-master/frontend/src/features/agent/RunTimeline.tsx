import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import type { RunRead } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { usePolling } from '../../hooks/usePolling';

const terminalRunStatuses = new Set(['succeeded', 'failed', 'partial', 'cancelled']);

interface RunTimelineProps {
  runId: number | null;
  refreshToken: number;
  onRunLoaded: (run: RunRead | null) => void;
}

export function RunTimeline({ runId, refreshToken, onRunLoaded }: RunTimelineProps) {
  const [run, setRun] = useState<RunRead | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRun = useCallback(async () => {
    if (runId == null) {
      setRun(null);
      onRunLoaded(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextRun = await api.getRun(runId);
      setRun(nextRun);
      onRunLoaded(nextRun);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Failed to load run');
    } finally {
      setLoading(false);
    }
  }, [onRunLoaded, runId]);

  useEffect(() => {
    void loadRun();
  }, [loadRun, refreshToken]);

  usePolling(loadRun, 2200, Boolean(runId && run && !terminalRunStatuses.has(run.status)));

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Runtime telemetry</p>
        <h2>{run ? `Run #${run.id}` : 'No active run'}</h2>
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={error} />
        {loading && <LoadingBlock label="Loading run" />}
        {!run && !loading && (
          <EmptyState title="No run selected" body="Agent responses will attach a run timeline here." />
        )}
        {run && (
          <>
            <div className="meta-row">
              <StatusBadge status={run.status} tone="run" />
              <span>{run.workflow}</span>
              {run.error_message && <span>{run.error_message}</span>}
            </div>
            <div className="timeline">
              {run.events.map((event) => (
                <article className="timeline-event" key={event.id}>
                  <div className="meta-row">
                    <span>#{event.sequence}</span>
                    <span>{event.event_type}</span>
                    <StatusBadge status={event.level} />
                    <span>{new Date(event.created_at).toLocaleTimeString()}</span>
                  </div>
                  {Object.keys(event.payload).length > 0 && <pre>{JSON.stringify(event.payload, null, 2)}</pre>}
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

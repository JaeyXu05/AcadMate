import { useCallback } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';

interface ThreadListProps {
  selectedThreadId: number | null;
  refreshToken: number;
  onSelectThread: (threadId: number) => void;
  onArchiveThread?: (threadId: number) => Promise<void> | void;
  variant?: 'panel' | 'sidebar';
}

export function ThreadList({ selectedThreadId, refreshToken, onSelectThread, onArchiveThread, variant = 'panel' }: ThreadListProps) {
  const loader = useCallback(() => api.listThreads(), []);
  const { data, loading, error } = useAsyncResource(loader, [refreshToken]);
  const body = (
    <div className="thread-list stack">
      <ErrorBanner message={error} />
      {loading && <LoadingBlock label="Loading threads" />}
      {!loading && !data?.length && (
        <EmptyState title="No threads yet" body="Send an agent message to open the first research thread." />
      )}
      {data?.map((thread) => (
        <article className={`thread-card ${thread.id === selectedThreadId ? 'is-selected' : ''}`} key={thread.id}>
          <button className="card-button-reset" type="button" onClick={() => onSelectThread(thread.id)}>
            <div className="meta-row">
              <span>#{thread.id}</span>
              <StatusBadge status={thread.status} />
            </div>
            <h3>{thread.title}</h3>
            <div className="meta-row">
              <span>{new Date(thread.updated_at).toLocaleString()}</span>
              {thread.current_focus_paper_id && <span>paper #{thread.current_focus_paper_id}</span>}
            </div>
          </button>
          {onArchiveThread && (
            <div className="thread-card__actions">
              <button className="ghost-danger-button" type="button" onClick={() => void onArchiveThread(thread.id)}>
                Delete
              </button>
            </div>
          )}
        </article>
      ))}
    </div>
  );

  if (variant === 'sidebar') {
    return body;
  }

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Threads</p>
        <h2>Mission log</h2>
      </div>
      <div className="panel-body">{body}</div>
    </section>
  );
}

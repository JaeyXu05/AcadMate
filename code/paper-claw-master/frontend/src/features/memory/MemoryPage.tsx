import { useCallback } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';

interface MemoryPageProps {
  refreshToken: number;
}

export function MemoryPage({ refreshToken }: MemoryPageProps) {
  const loader = useCallback(() => api.listMemories(), []);
  const { data, loading, error } = useAsyncResource(loader, [refreshToken]);
  const memories = data ?? [];

  return (
    <div className="memory-workspace">
      <header className="workspace-header">
        <p className="eyebrow">Memory</p>
        <h1>Long-term memory</h1>
        <p>Read-only view of DeepAgents-native memories stored in the Paper Claw database.</p>
      </header>
      <div className="memory-grid">
        <aside className="section-sidebar memory-index">
          <ErrorBanner message={error} />
          {loading && <LoadingBlock label="Loading memories" />}
          {!loading && !memories.length && <EmptyState title="No memories yet" body="Agent-created long-term memories will appear here." />}
          {memories.map((memory) => (
            <article className="memory-card" key={memory.id}>
              <div className="meta-row">
                <span>#{memory.id}</span>
                <StatusBadge status={memory.status} />
                <span>{memory.memory_type}</span>
              </div>
              <h3>{memory.title ?? memory.path}</h3>
              <div className="meta-row">
                <span>{memory.scope_type}</span>
                {memory.scope_id && <span>{memory.scope_id}</span>}
                {memory.paper_id && <span>paper #{memory.paper_id}</span>}
              </div>
            </article>
          ))}
        </aside>
        <main className="workspace-main memory-detail-list">
          {!memories.length && !loading && <EmptyState title="Memory detail" body="Select-style editing is not enabled yet; this first version shows all memory contents read-only." />}
          {memories.map((memory) => (
            <article className="panel memory-detail" key={memory.id}>
              <div className="panel-header">
                <p className="eyebrow">{memory.memory_type}</p>
                <h2>{memory.title ?? memory.path}</h2>
              </div>
              <div className="panel-body stack">
                <div className="meta-row">
                  <span>{memory.path}</span>
                  <span>source {memory.source}</span>
                  <span>updated {new Date(memory.updated_at).toLocaleString()}</span>
                </div>
                <p>{memory.content_text}</p>
                {memory.content_json && (
                  <details className="dossier-record">
                    <summary>Structured content</summary>
                    <pre>{JSON.stringify(memory.content_json, null, 2)}</pre>
                  </details>
                )}
                {!!Object.keys(memory.metadata).length && (
                  <details className="dossier-record">
                    <summary>Metadata</summary>
                    <pre>{JSON.stringify(memory.metadata, null, 2)}</pre>
                  </details>
                )}
              </div>
            </article>
          ))}
        </main>
      </div>
    </div>
  );
}

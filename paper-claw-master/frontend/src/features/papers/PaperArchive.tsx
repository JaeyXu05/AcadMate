import { useCallback } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';

interface PaperArchiveProps {
  selectedPaperId: number | null;
  activePaperId: number | null;
  refreshToken: number;
  onSelectPaper: (paperId: number) => void;
  onSetActivePaper: (paperId: number) => void;
}

export function PaperArchive({ selectedPaperId, activePaperId, refreshToken, onSelectPaper, onSetActivePaper }: PaperArchiveProps) {
  const loader = useCallback(() => api.listPapers(), []);
  const { data, loading, error } = useAsyncResource(loader, [refreshToken]);

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Archive</p>
        <h2>Paper index</h2>
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={error} />
        {loading && <LoadingBlock label="Loading papers" />}
        {!loading && !data?.length && (
          <EmptyState title="Archive empty" body="Ask the agent to find or acquire a paper; confirmed papers will appear here." />
        )}
        {data?.map((paper) => (
          <article className={`archive-card ${paper.id === selectedPaperId ? 'is-selected' : ''}`} key={paper.id}>
            <button className="card-button-reset" onClick={() => onSelectPaper(paper.id)}>
              <div className="meta-row">
                <span>#{paper.id}</span>
                <StatusBadge status={paper.status} tone="paper" />
                {paper.id === activePaperId && <span>pinned</span>}
              </div>
              <h3>{paper.title}</h3>
              <div className="meta-row">
                {paper.year && <span>{paper.year}</span>}
                {paper.venue && <span>{paper.venue}</span>}
              </div>
            </button>
            <div className="button-row">
              <button className="secondary-button" onClick={() => onSelectPaper(paper.id)}>Open dossier</button>
              <button className="chip-button" onClick={() => onSetActivePaper(paper.id)}>Pin context</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

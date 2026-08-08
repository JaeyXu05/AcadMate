import { useCallback, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';
import { downloadMarkdown } from '../../utils/markdownExport';
import { MarkdownMessage } from '../agent/MarkdownMessage';
import { ArtifactUpload } from './ArtifactUpload';

interface PaperDetailProps {
  paperId: number | null;
  activeRunId: number | null;
  refreshToken: number;
  onSelectReport: (reportId: number) => void;
  onRefresh: () => void;
}

type DossierRecord = Record<string, unknown>;

export function PaperDetail({ paperId, activeRunId, refreshToken, onSelectReport, onRefresh }: PaperDetailProps) {
  const loader = useCallback(async () => {
    if (paperId == null) {
      return null;
    }
    return api.getPaper(paperId);
  }, [paperId]);
  const { data: paper, loading, error, reload } = useAsyncResource(loader, [refreshToken]);
  const [selectedChunkIndex, setSelectedChunkIndex] = useState(0);
  const latestReadyDocument = [...(paper?.processed_documents ?? [])]
    .reverse()
    .find((document: DossierRecord) => document.status === 'ready' && typeof document.content_markdown === 'string' && document.content_markdown.length > 0);
  const latestChunks = useMemo(() => Array.isArray(latestReadyDocument?.chunks) ? (latestReadyDocument.chunks as DossierRecord[]) : [], [latestReadyDocument]);
  const safeSelectedChunkIndex = latestChunks.length ? Math.min(selectedChunkIndex, latestChunks.length - 1) : 0;

  const refresh = () => {
    reload();
    onRefresh();
  };

  return (
    <section className="panel paper-dossier">
      <div className="panel-header paper-dossier-header">
        <div>
          <p className="eyebrow">Paper dossier</p>
          <h2>{paper?.title ?? 'No paper selected'}</h2>
        </div>
        {paper && (
          <div className="paper-dossier-stats" aria-label="Paper record counts">
            <Metric label="artifacts" value={paper.artifacts.length} />
            <Metric label="parses" value={paper.parse_jobs.length} />
            <Metric label="chunks" value={latestChunks.length} />
          </div>
        )}
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={error} />
        {loading && paperId && <LoadingBlock label="Loading paper" />}
        {!paper && !loading && (
          <EmptyState title="Open a dossier" body="Select a paper from the archive or pin one as active agent context." />
        )}
        {paper && (
          <>
            <div className="paper-brief">
              <div className="meta-row">
                <span>paper #{paper.id}</span>
                <StatusBadge status={paper.status} />
                {paper.year && <span>{paper.year}</span>}
                {paper.venue && <span>{paper.venue}</span>}
              </div>
              {paper.abstract && <p>{paper.abstract}</p>}
              <div className="button-row">
                <button
                  className="secondary-button"
                  disabled={!latestReadyDocument}
                  onClick={() => downloadMarkdown(paper.title, String(latestReadyDocument?.content_markdown ?? ''))}
                  type="button"
                >
                  Export parsed markdown
                </button>
              </div>
            </div>

            <div className="dossier-grid">
              <CompactDossierSection title="Identifiers" items={paper.identifiers} fields={["type", "value", "is_primary"]} />
              <CompactDossierSection title="Source records" items={paper.source_records} fields={["source", "source_record_id", "source_url", "is_primary"]} />
              <CompactDossierSection title="Artifacts" items={paper.artifacts} fields={["role", "kind", "status", "storage_uri"]} />
              <CompactDossierSection title="Parse jobs" items={paper.parse_jobs} fields={["strategy", "status", "error_message"]} />
              <CompactDossierSection title="Processed" items={paper.processed_documents} fields={["id", "version", "status", "quality_status"]} />
            </div>

            <div className="paper-document-grid">
              <div className="stack">
                <SectionHeading title="Parsed document" meta={latestReadyDocument ? `ready #${String(latestReadyDocument.id)}` : undefined} />
                {latestReadyDocument ? (
                  <details className="dossier-record parsed-document" open>
                    <summary>{String(latestReadyDocument.quality_summary ?? 'Normalized markdown')}</summary>
                    <MarkdownMessage content={String(latestReadyDocument.content_markdown)} />
                  </details>
                ) : (
                  <p className="meta-row">No ready parsed document.</p>
                )}
              </div>
              <div className="stack">
                <SectionHeading title="Chunks" meta={latestChunks.length ? `${latestChunks.length} chunks` : undefined} />
                <ChunkList chunks={latestChunks} selectedIndex={safeSelectedChunkIndex} onSelect={setSelectedChunkIndex} />
              </div>
            </div>

            <div className="stack">
              <h3>Reports</h3>
              {!paper.reports.length && <p className="meta-row">No reports linked.</p>}
              {paper.reports.map((report) => {
                const id = Number(report.id);
                return (
                  <button className="report-card" key={id} onClick={() => onSelectReport(id)}>
                    <div className="meta-row">
                      <span>#{String(report.id)}</span>
                      {typeof report.status === 'string' && <StatusBadge status={report.status} />}
                      {typeof report.report_type === 'string' && <span>{report.report_type}</span>}
                    </div>
                    <h3>{String(report.title ?? 'Untitled report')}</h3>
                  </button>
                );
              })}
            </div>
            <div className="stack">
              <h3>Attach source material</h3>
              <ArtifactUpload paperId={paper.id} activeRunId={activeRunId} onUploaded={refresh} />
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="paper-dossier-metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function SectionHeading({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="section-heading-row">
      <h3>{title}</h3>
      {meta && <span>{meta}</span>}
    </div>
  );
}

function CompactDossierSection({ title, items, fields }: { title: string; items: DossierRecord[]; fields: string[] }) {
  return (
    <div className="compact-dossier-section">
      <SectionHeading title={title} meta={`${items.length}`} />
      {!items.length && <p className="meta-row">No records.</p>}
      <div className="compact-record-list">
        {items.map((item, index) => (
          <details className="compact-record" key={index}>
            <summary>
              <span>{recordTitle(item, index)}</span>
              {typeof item.status === 'string' && <StatusBadge status={item.status} />}
            </summary>
            <dl>
              {fields.map((field) => field in item && (
                <div key={field}>
                  <dt>{field}</dt>
                  <dd title={String(item[field] ?? '')}>{formatValue(item[field])}</dd>
                </div>
              ))}
            </dl>
            {hasHiddenFields(item, fields) && <pre>{JSON.stringify(item, null, 2)}</pre>}
          </details>
        ))}
      </div>
    </div>
  );
}

function ChunkList({ chunks, selectedIndex, onSelect }: { chunks: DossierRecord[]; selectedIndex: number; onSelect: (index: number) => void }) {
  if (!chunks.length) {
    return <p className="meta-row">No chunks available.</p>;
  }
  const selectedChunk = chunks[selectedIndex] ?? chunks[0];
  const content = String(selectedChunk.content_text ?? '').trim();

  return (
    <div className="chunk-browser">
      <div className="chunk-index-list" aria-label="Document chunks">
        {chunks.map((chunk, index) => (
          <button
            className={`chunk-index-button ${index === selectedIndex ? 'is-selected' : ''}`}
            key={String(chunk.id ?? chunk.chunk_key ?? index)}
            onClick={() => onSelect(index)}
            type="button"
          >
            <span>#{String(chunk.chunk_index ?? index + 1)}</span>
            <strong>{chunkHeading(chunk)}</strong>
          </button>
        ))}
      </div>
      <article className="chunk-card chunk-reader">
        <div className="chunk-card-header">
          <span className="chunk-index">#{String(selectedChunk.chunk_index ?? selectedIndex + 1)}</span>
          <span className="chunk-heading">{chunkHeading(selectedChunk)}</span>
          {typeof selectedChunk.role === 'string' && <span className="chunk-role">{selectedChunk.role}</span>}
          {selectedChunk.token_estimate != null && <span className="chunk-tokens">{String(selectedChunk.token_estimate)} tok</span>}
        </div>
        <pre className="chunk-content">{content || 'Empty chunk content'}</pre>
      </article>
    </div>
  );
}

function recordTitle(item: DossierRecord, index: number): string {
  const label = item.title ?? item.role ?? item.kind ?? item.strategy ?? item.type ?? item.id ?? index + 1;
  return String(label);
}

function chunkHeading(chunk: DossierRecord): string {
  if (Array.isArray(chunk.heading_path) && chunk.heading_path.length) {
    return chunk.heading_path.map(String).join(' / ');
  }
  return String(chunk.chunk_key ?? 'untitled chunk');
}

function formatValue(value: unknown): string {
  if (value == null || value === '') {
    return '—';
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  if (Array.isArray(value)) {
    return value.map(String).join(' / ');
  }
  return String(value);
}

function hasHiddenFields(item: DossierRecord, fields: string[]): boolean {
  return Object.keys(item).some((key) => !fields.includes(key) && key !== 'content_markdown' && key !== 'chunks');
}

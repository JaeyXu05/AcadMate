import { useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';
import { downloadMarkdown } from '../../utils/markdownExport';
import type { JsonObject, JsonValue } from '../../api/types';

interface ReportReaderProps {
  reportId: number | null;
  onSelectPaper: (paperId: number) => void;
  onDeleteReport: (reportId: number) => Promise<void> | void;
}

function ReportProvenance({ jsonContent, sourceRefs }: { jsonContent: JsonObject | null; sourceRefs: unknown[] }) {
  const items = [
    ['Context', stringValue(jsonContent?.context_strategy)],
    ['Instruction', stringValue(jsonContent?.instruction_type)],
    ['Validation', jsonContent?.validation_passed === true ? 'passed' : jsonContent?.validation_passed === false ? 'failed' : null],
    ['Regenerated', jsonContent?.regeneration_used === true ? 'yes' : jsonContent?.regeneration_used === false ? 'no' : null],
    ['Sources', sourceRefs.length ? `${sourceRefs.length} linked source${sourceRefs.length === 1 ? '' : 's'}` : null],
  ].filter((item): item is [string, string] => Boolean(item[1]));

  if (!items.length && !sourceRefs.length) {
    return null;
  }

  return (
    <div className="report-provenance">
      <div>
        <p className="eyebrow">Generation record</p>
        <h3>Full-document source trail</h3>
      </div>
      <div className="report-provenance-grid">
        {items.map(([label, value]) => (
          <div className="report-provenance-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {sourceRefs.length > 0 && (
        <details className="dossier-record">
          <summary>Source references</summary>
          <pre>{JSON.stringify(sourceRefs, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

function stringValue(value: JsonValue | undefined): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

export function ReportReader({ reportId, onSelectPaper, onDeleteReport }: ReportReaderProps) {
  const loader = useCallback(async () => {
    if (reportId == null) {
      return null;
    }
    return api.getReport(reportId);
  }, [reportId]);
  const { data: report, loading, error } = useAsyncResource(loader, [reportId]);

  return (
    <section className="panel report-reader">
      <div className="panel-header">
        <p className="eyebrow">Report reader</p>
        <h2>{report?.title ?? 'No report selected'}</h2>
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={error} />
        {loading && reportId && <LoadingBlock label="Loading report" />}
        {!report && !loading && (
          <EmptyState title="Open a brief" body="Select a report from the evidence briefs index." />
        )}
        {report && (
          <div className="report-reader-layout">
            <div className="meta-row">
              <span>report #{report.id}</span>
              <StatusBadge status={report.status} />
              <span>{report.report_type}</span>
              <span>{report.source_scope}</span>
            </div>
            <div className="reader-actions">
              {report.paper_id && (
                <button className="secondary-button" type="button" onClick={() => onSelectPaper(report.paper_id!)}>Open linked paper</button>
              )}
              <button
                className="secondary-button"
                disabled={!report.markdown_content}
                onClick={() => downloadMarkdown(report.paper_title ?? report.title, report.markdown_content ?? '', { report: true })}
                type="button"
              >
                Export report markdown
              </button>
              <button className="ghost-danger-button" type="button" onClick={() => void onDeleteReport(report.id)}>
                Delete report
              </button>
            </div>
            <div className="report-content markdown-message">
              {report.markdown_content ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.markdown_content}</ReactMarkdown> : 'No markdown content.'}
            </div>
            {report.evidence.length ? (
              <div className="stack">
                <h3>Evidence</h3>
                {report.evidence.map((item, index) => (
                  <details className="dossier-record" key={index}>
                    <summary>{String(item.evidence_type ?? item.id ?? index + 1)}</summary>
                    <pre>{JSON.stringify(item, null, 2)}</pre>
                  </details>
                ))}
              </div>
            ) : (
              <ReportProvenance jsonContent={report.json_content} sourceRefs={report.source_refs} />
            )}
          </div>
        )}
      </div>
    </section>
  );
}

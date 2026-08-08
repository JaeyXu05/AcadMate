import { useCallback } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { StatusBadge } from '../../components/StatusBadge';
import { useAsyncResource } from '../../hooks/useAsyncResource';

interface ReportIndexProps {
  selectedReportId: number | null;
  refreshToken: number;
  errorMessage: string | null;
  onSelectReport: (reportId: number) => void;
  onDeleteReport: (reportId: number) => Promise<void> | void;
}

export function ReportIndex({ selectedReportId, refreshToken, errorMessage, onSelectReport, onDeleteReport }: ReportIndexProps) {
  const loader = useCallback(() => api.listReports(), []);
  const { data, loading, error } = useAsyncResource(loader, [refreshToken]);

  return (
    <section className="panel">
      <div className="panel-header">
        <p className="eyebrow">Reports</p>
        <h2>Evidence briefs</h2>
      </div>
      <div className="panel-body stack">
        <ErrorBanner message={errorMessage} />
        <ErrorBanner message={error} />
        {loading && <LoadingBlock label="Loading reports" />}
        {!loading && !data?.length && (
          <EmptyState title="No reports" body="Ask the agent for a summary, critique, or comparison to create report artifacts." />
        )}
        {data?.map((report) => (
          <article className={`report-card ${report.id === selectedReportId ? 'is-selected' : ''}`} key={report.id}>
            <button className="card-button-reset" type="button" onClick={() => onSelectReport(report.id)}>
              <div className="meta-row">
                <span>#{report.id}</span>
                <StatusBadge status={report.status} />
                <span>{report.report_type}</span>
              </div>
              <h3>{report.title}</h3>
              <div className="meta-row">
                <span>{report.source_scope}</span>
                {report.paper_id && <span>paper #{report.paper_id}</span>}
              </div>
            </button>
            <div className="card-actions">
              <button className="ghost-danger-button" type="button" onClick={() => void onDeleteReport(report.id)}>
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

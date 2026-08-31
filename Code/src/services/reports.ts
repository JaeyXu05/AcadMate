import api from './axios';

export type ReportPeriod = 'daily' | 'weekly' | 'monthly';

export interface ReportPreferences {
  daily_enabled: boolean;
  weekly_enabled: boolean;
  monthly_enabled: boolean;
  email_enabled: boolean;
  daily_time: string;
  weekly_day: number;
  monthly_day: number;
  timezone: string;
  smtp_configured: boolean;
}

export interface ProgressReport {
  id: number;
  period_type: ReportPeriod;
  period_start: string;
  period_end: string;
  title: string;
  content_markdown: string;
  metrics: Record<string, number>;
  evidence_refs: string[];
  review_status: string;
  generation?: {
    agent?: string;
    status?: string;
    reason?: string;
    config_source?: string;
    provider?: string;
    model?: string;
    base_host?: string;
  };
  created_at: string;
}

export interface EmailOutboxItem {
  id: number;
  recipient: string;
  subject: string;
  kind: string;
  status: string;
  scheduled_at?: string;
  sent_at?: string;
  error?: string;
  created_at: string;
}

export interface PresentationJob {
  id: number;
  report_id: number;
  status: 'queued' | 'generating' | 'succeeded' | 'failed' | string;
  template: string;
  slide_count: number;
  title: string;
  error?: string | null;
  download_url?: string | null;
  created_at: string;
  completed_at?: string | null;
}

export async function getPreferences(): Promise<ReportPreferences> {
  return (await api.get('/reports/preferences')).data;
}

export async function savePreferences(input: Omit<ReportPreferences, 'smtp_configured'>): Promise<void> {
  await api.put('/reports/preferences', input);
}

export async function listReports(): Promise<ProgressReport[]> {
  return (await api.get('/reports')).data;
}

export async function generateReport(period_type: ReportPeriod, send_email = false): Promise<ProgressReport> {
  // The server keeps a report AgentRun alive for up to 420s and reconciles a
  // late result.  Keep the browser timeout above that ceiling so a healthy
  // long generation is not turned into a client-side false timeout.
  return (await api.post('/reports/generate', { period_type, send_email }, { timeout: 450000 })).data;
}

export async function createPresentation(reportId: number, input?: { template?: string; slide_count?: number }): Promise<PresentationJob> {
  return (await api.post(`/reports/${reportId}/presentation`, input || {}, { timeout: 15000 })).data;
}

export async function getPresentation(jobId: number): Promise<PresentationJob> {
  return (await api.get(`/reports/presentations/${jobId}`)).data;
}

export async function downloadPresentation(jobId: number): Promise<Blob> {
  return (await api.get(`/reports/presentations/${jobId}/download`, { responseType: 'blob', timeout: 30000 })).data;
}

export async function getOutbox(): Promise<{ smtp_configured: boolean; items: EmailOutboxItem[] }> {
  return (await api.get('/reports/outbox')).data;
}

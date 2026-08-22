import { useCallback } from 'react';
import { api } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorBanner } from '../../components/ErrorBanner';
import { LoadingBlock } from '../../components/LoadingBlock';
import { useAsyncResource } from '../../hooks/useAsyncResource';

export function SettingPage() {
  const loader = useCallback(() => api.getRuntimeSettings(), []);
  const { data: settings, loading, error } = useAsyncResource(loader, []);

  return (
    <main className="setting-workspace">
      <header className="workspace-header">
        <p className="eyebrow">Settings</p>
        <h1>Runtime configuration</h1>
        <p>Read-only status from environment-backed settings. Secrets are shown only as configured or missing.</p>
      </header>
      <ErrorBanner message={error} />
      {loading && <LoadingBlock label="Loading settings" />}
      {!settings && !loading && <EmptyState title="No settings loaded" body="Runtime settings could not be loaded." />}
      {settings && (
        <div className="settings-grid">
          <SettingsCard
            title="System"
            rows={[
              ['environment', settings.environment],
              ['database', settings.database_configured ? 'configured' : 'missing'],
              ['data dir', settings.data_dir],
              ['storage root', settings.storage_root ?? 'default'],
            ]}
          />
          <SettingsCard title="Chat model" rows={settingsRows(settings.chat)} />
          <SettingsCard title="Embedding model" rows={settingsRows(settings.embedding)} />
          <SettingsCard title="arXiv" rows={settingsRows(settings.arxiv)} />
          <SettingsCard title="OpenAlex" rows={settingsRows(settings.openalex)} />
          <SettingsCard title="Parsing" rows={settingsRows(settings.parsing)} />
        </div>
      )}
    </main>
  );
}

function SettingsCard({ title, rows }: { title: string; rows: Array<[string, unknown]> }) {
  return (
    <section className="panel settings-card">
      <div className="panel-header">
        <p className="eyebrow">Config</p>
        <h2>{title}</h2>
      </div>
      <div className="panel-body settings-table">
        {rows.map(([key, value]) => (
          <div className="settings-row" key={key}>
            <span>{key}</span>
            <strong>{formatSettingValue(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function settingsRows(record: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(record);
}

function formatSettingValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return 'missing';
  }
  if (typeof value === 'boolean') {
    return value ? 'configured' : 'missing';
  }
  return String(value);
}

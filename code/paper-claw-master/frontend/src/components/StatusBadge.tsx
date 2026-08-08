interface StatusBadgeProps {
  status: string;
  tone?: 'run' | 'paper' | 'neutral';
}

export function StatusBadge({ status, tone = 'neutral' }: StatusBadgeProps) {
  return <span className={`status-badge status-${normalizeStatus(status)} status-tone-${tone}`}>{status}</span>;
}

function normalizeStatus(status: string): string {
  return status.toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

interface EmptyStateProps {
  eyebrow?: string;
  title: string;
  body: string;
}

export function EmptyState({ eyebrow = 'No signal', title, body }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="eyebrow">{eyebrow}</span>
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}

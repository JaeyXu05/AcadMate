interface LoadingBlockProps {
  label?: string;
}

export function LoadingBlock({ label = 'Loading signal' }: LoadingBlockProps) {
  return (
    <div className="loading-block" aria-live="polite">
      <span />
      <span />
      <span />
      <strong>{label}</strong>
    </div>
  );
}

import { FormEvent, KeyboardEvent, useState } from 'react';

interface MessageComposerProps {
  disabled?: boolean;
  activePaperId: number | null;
  canCancelRun?: boolean;
  onSubmit: (message: string) => Promise<void>;
  onCancelRun?: () => Promise<void> | void;
}

export function MessageComposer({ disabled = false, activePaperId, canCancelRun = false, onSubmit, onCancelRun }: MessageComposerProps) {
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (canCancelRun) {
      if (!onCancelRun) {
        return;
      }
      setCancelling(true);
      try {
        await onCancelRun();
      } finally {
        setCancelling(false);
      }
      return;
    }
    const trimmed = message.trim();
    if (!trimmed) {
      return;
    }
    setMessage('');
    setSubmitting(true);
    try {
      await onSubmit(trimmed);
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !canCancelRun) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <form className="composer chat-composer" onSubmit={submit}>
      <div className="chat-composer__box">
        <label>
          <span className="chat-composer__label">
            Ask Paper Claw
            {activePaperId && <span className="active-context-chip">paper #{activePaperId}</span>}
          </span>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask the agent to find, acquire, parse, compare, or review papers..."
            disabled={disabled || submitting || canCancelRun}
            rows={3}
          />
        </label>
        <div className="chat-composer__footer">
          <span className="chat-composer__hint">Enter to send · Shift+Enter for newline</span>
          <button className={canCancelRun ? 'danger-button' : 'primary-button'} type="submit" disabled={disabled || cancelling || (!canCancelRun && (submitting || !message.trim()))}>
            {canCancelRun ? (cancelling ? 'Cancelling...' : 'Cancel run') : submitting ? 'Streaming...' : 'Send'}
          </button>
        </div>
      </div>
    </form>
  );
}

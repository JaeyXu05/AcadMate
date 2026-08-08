import type { MessageRead, RunRead } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { AgentActivity } from './AgentActivity';
import { MarkdownMessage } from './MarkdownMessage';

interface MessageTranscriptProps {
  messages: MessageRead[];
  runs?: RunRead[];
}

export function MessageTranscript({ messages, runs = [] }: MessageTranscriptProps) {
  const runsById = new Map(runs.map((run) => [run.id, run]));

  if (!messages.length) {
    return (
      <EmptyState
        eyebrow="Transcript"
        title="Awaiting first instruction"
        body="Use the composer below to ask the agent to find, acquire, parse, compare, or review papers."
      />
    );
  }

  return (
    <div className="transcript">
      {messages.map((message) => {
        const run = message.run_id == null ? undefined : runsById.get(message.run_id);
        return (
          <article className={`message message-${message.role}`} key={message.id}>
            <div className="meta-row">
              <span>{message.role}</span>
              <span>{message.source}</span>
              <span>{new Date(message.created_at).toLocaleString()}</span>
            </div>
            {message.role === 'assistant' && run && <AgentActivity run={run} />}
            {message.content_text && (message.role === 'assistant' ? <MarkdownMessage content={message.content_text} /> : <p>{message.content_text}</p>)}
            {message.content_json && (
              <details>
                <summary>payload</summary>
                <pre>{JSON.stringify(message.content_json, null, 2)}</pre>
              </details>
            )}
          </article>
        );
      })}
    </div>
  );
}

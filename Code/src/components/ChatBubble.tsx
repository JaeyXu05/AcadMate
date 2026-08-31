import type { AgentStage, ChatMessage } from '../types/search';
import styles from './ChatWindow.module.css';

interface ChatBubbleProps {
  message: ChatMessage;
}

function stageClassName(eventType: string): string {
  if (eventType === 'REVIEW_FAILED' || eventType === 'WORKFLOW_FAILED') {
    return styles.stageFail;
  }
  if (eventType === 'TASK_RETRY') {
    return styles.stageRetry;
  }
  if (eventType === 'REVIEW_STARTED' || eventType === 'REVIEW_PASSED') {
    return styles.stageReview;
  }
  return '';
}

function StageTimeline({ stages }: { stages: AgentStage[] }) {
  if (!stages.length) return null;
  return (
    <ol className={styles.stageTimeline}>
      {stages.map((stage, index) => (
        <li
          key={`${stage.event_type}-${index}`}
          className={`${styles.stageItem} ${stageClassName(stage.event_type)}`}
        >
          <span className={styles.stageType}>{stage.event_type}</span>
          <span className={styles.stageSummary}>{stage.summary}</span>
          {(stage.sender || stage.receiver) && (
            <span className={styles.stageRoute}>
              {[stage.sender, stage.receiver].filter(Boolean).join(' → ')}
            </span>
          )}
          {(stage.evidence_refs?.length ?? 0) > 0 && (
            <details className={styles.stageEvidence}>
              <summary>Evidence {stage.evidence_refs!.length}</summary>
              {stage.evidence_refs!.map((ref) => (
                <code key={ref}>{ref}</code>
              ))}
            </details>
          )}
          {stage.payload && Object.keys(stage.payload).length > 0 && (
            <details className={styles.stageEvidence}>
              <summary>结构化事件详情</summary>
              <pre className={styles.stagePayload}>
                {JSON.stringify(stage.payload, null, 2)}
              </pre>
            </details>
          )}
        </li>
      ))}
    </ol>
  );
}

function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const isStreaming = message.isStreaming ?? false;
  // While streaming, SearchPage renders the live timeline separately.  Do
  // not render the same stages inside the bubble as well.
  const stages = isStreaming ? [] : (message.stages ?? []);

  return (
    <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAgent}`}>
      {!isUser && stages.length > 0 && <StageTimeline stages={stages} />}
      <div className={styles.bubbleContent}>
        {message.content}
        {isStreaming && <span className={styles.cursor}>▌</span>}
      </div>
      {!isUser && message.advisors && message.advisors.length > 0 && (
        <div className={styles.bubbleResultTag}>
          已推荐 {message.advisors.length} 位导师 →
        </div>
      )}
    </div>
  );
}

export default ChatBubble;
export { StageTimeline };

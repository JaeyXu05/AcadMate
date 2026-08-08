import type { ChatMessage } from '../types/search';
import styles from './ChatWindow.module.css';

interface ChatBubbleProps {
  message: ChatMessage;
}

function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const isStreaming = message.isStreaming ?? false;

  return (
    <div className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleAgent}`}>
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
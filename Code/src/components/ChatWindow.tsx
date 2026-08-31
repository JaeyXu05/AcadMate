import { useState, useRef, useEffect } from 'react';
import { Input, Button, App } from 'antd';
import { Send, Plus } from 'lucide-react';
import { useSearchStore } from '../stores/searchStore';
import ChatBubble from './ChatBubble';
import styles from './ChatWindow.module.css';

const { TextArea } = Input;

function ChatWindow() {
  const { modal } = App.useApp();
  const [inputValue, setInputValue] = useState('');
  const chatHistory = useSearchStore((s) => s.chatHistory);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const pendingQuery = useSearchStore((s) => s.pendingQuery);
  const clearChat = useSearchStore((s) => s.clearChat);
  const listEndRef = useRef<HTMLDivElement>(null);

  const handleNewChat = () => {
    modal.confirm({
      title: '开始新对话',
      content: '将清空当前对话与检索结果，确定继续吗？',
      okText: '清空并开始',
      cancelText: '取消',
      centered: true,
      onOk: () => clearChat(),
    });
  };

  // 新消息自动滚到底部
  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // 监听 pendingQuery（来自历史记录恢复 / 云图联动）→ 自动发起一次检索。
  // 若正在流式，暂不清空 pendingQuery，等 isStreaming 变 false 后再消费，
  // 避免在流式中先清空再跳过导致恢复 query 永久丢失。
  useEffect(() => {
    if (!pendingQuery) return;
    if (useSearchStore.getState().isStreaming) return;
    useSearchStore.getState().setPendingQuery(null);
    useSearchStore.getState().addUserMessage(pendingQuery);
  }, [pendingQuery, isStreaming]);

  const handleSend = () => {
    const trimmed = inputValue.trim();
    if (!trimmed || isStreaming) return;
    setInputValue('');

    // 触发 SSE 由 SearchPage 的 useEffect 监听新 user 消息来调用
    useSearchStore.getState().addUserMessage(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={styles.chatWindow}>
      <div className={styles.chatHeader}>
        <span className={styles.chatTitle}>智能体对话</span>
        {chatHistory.length > 0 && (
          <button
            className={styles.newChatBtn}
            onClick={handleNewChat}
            disabled={isStreaming}
            title="开始新对话"
          >
            <Plus size={14} strokeWidth={1.5} className="text-slate-600" />
            新对话
          </button>
        )}
      </div>

      <div className={styles.chatBody}>
        {chatHistory.length === 0 ? (
          <div className={styles.chatEmpty}>
            <div className={styles.chatEmptyIcon} />
            <div className={styles.chatEmptyText}>
              描述你想找的导师方向，我来为你推荐
            </div>
            <div className={styles.chatEmptyHint}>
              例如：找计算机视觉方向的导师、论文多的教授、对本科生友好的老师
            </div>
          </div>
        ) : (
          <div className={styles.chatList}>
            {chatHistory.map((msg) => (
              <ChatBubble key={msg.id} message={msg} />
            ))}
            <div ref={listEndRef} />
          </div>
        )}
      </div>

      <div className={styles.chatFooter}>
        <TextArea
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="描述你想找的导师方向…"
          autoSize={{ minRows: 6, maxRows: 12 }}
          disabled={isStreaming}
          className="input-quiet"
          style={{ resize: 'none', fontSize: 18, padding: '14px 16px' }}
        />
        <Button
          type="primary"
          icon={<Send size={14} strokeWidth={1.5} className="text-slate-600" />}
          onClick={handleSend}
          loading={isStreaming}
          disabled={!inputValue.trim() || isStreaming}
          style={{ height: 44, fontSize: 16 }}
        >
          发送
        </Button>
      </div>
    </div>
  );
}

export default ChatWindow;
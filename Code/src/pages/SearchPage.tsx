import { useEffect, useRef, useMemo, useState } from 'react';
import { Empty, Skeleton, Alert } from 'antd';
import { useSearchStore } from '../stores/searchStore';
import { useSettingsStore } from '../stores/settingsStore';
import { chatWithAgent } from '../services/agent';
import { recordSearch, recordChat } from '../services/user';
import type { Advisor, ChatMessage, SortBy } from '../types/search';
import ResizableSplit from '../components/ResizableSplit';
import SortSelector from '../components/SortSelector';
import AdvisorCard from '../components/AdvisorCard';
import ChatWindow from '../components/ChatWindow';
import styles from './SearchPage.module.css';

/** 根据排序方式对导师列表排序（纯前端） */
function sortAdvisors(list: Advisor[], by: SortBy): Advisor[] {
  const sorted = [...list];
  switch (by) {
    case 'match':
      sorted.sort((a, b) => b.matchScore - a.matchScore);
      break;
    case 'staffId':
      sorted.sort((a, b) => a.id.localeCompare(b.id));
      break;
    case 'papers':
      sorted.sort((a, b) => b.papers - a.papers);
      break;
    case 'department':
      sorted.sort((a, b) => a.department.localeCompare(b.department, 'zh'));
      break;
  }
  return sorted;
}

function SearchPage() {
  const chatHistory = useSearchStore((s) => s.chatHistory);
  const searchResults = useSearchStore((s) => s.searchResults);
  const sortBy = useSearchStore((s) => s.sortBy);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const splitRatio = useSearchStore((s) => s.splitRatio);
  const setSearchResults = useSearchStore((s) => s.setSearchResults);
  const setSortBy = useSearchStore((s) => s.setSortBy);
  const setSplitRatio = useSearchStore((s) => s.setSplitRatio);
  const appendAgentChunk = useSearchStore((s) => s.appendAgentChunk);
  const setAgentMessageComplete = useSearchStore((s) => s.setAgentMessageComplete);

  const defaultSort = useSettingsStore((s) => s.defaultSort);
  const cardDensity = useSettingsStore((s) => s.cardDensity);

  const [error, setError] = useState<string | null>(null);

  // 首次加载时用默认排序
  useEffect(() => {
    setSortBy(defaultSort as SortBy);
  }, []);

  // 监听新用户消息 → 触发 SSE
  const processingRef = useRef(false);
  const searchRecordedRef = useRef(false);

  useEffect(() => {
    if (chatHistory.length < 2) return;

    // addUserMessage 会同时 push userMsg + agentMsg，所以倒数第二个是 user，最后一个是 agent
    const userMsg = chatHistory[chatHistory.length - 2];
    const agentMsg = chatHistory[chatHistory.length - 1];

    if (userMsg.role !== 'user' || agentMsg.role !== 'agent' || !agentMsg.isStreaming) return;
    if (processingRef.current) return;

    processingRef.current = true;
    searchRecordedRef.current = false;
    setError(null);

    const agentId = agentMsg.id;
    const sessionId = useSearchStore.getState().sessionId;
    // 记录用户消息到 chat_history（失败静默，不阻断主流程）
    if (sessionId) {
      recordChat(sessionId, 'user', userMsg.content).catch(() => {});
    }

    chatWithAgent(
      userMsg.content,
      (event) => {
        switch (event.type) {
          case 'thinking':
            if (event.content) appendAgentChunk(agentId, event.content + '\n');
            break;
          case 'summary':
            if (event.content) appendAgentChunk(agentId, event.content);
            break;
          case 'result':
            if (event.advisors) {
              setSearchResults(event.advisors);
              setAgentMessageComplete(agentId, event.advisors);
              // 每轮检索只记一次 search_history
              if (!searchRecordedRef.current) {
                searchRecordedRef.current = true;
                recordSearch(userMsg.content, event.advisors.length).catch(() => {});
              }
            }
            break;
          case 'done':
            setAgentMessageComplete(agentId);
            // 记录 agent 最终回复到 chat_history
            {
              const finalAgentMsg = useSearchStore
                .getState()
                .chatHistory.find((m) => m.id === agentId);
              if (sessionId && finalAgentMsg?.content) {
                recordChat(sessionId, 'agent', finalAgentMsg.content).catch(() => {});
              }
            }
            processingRef.current = false;
            break;
          case 'error':
            appendAgentChunk(agentId, event.message ?? '发生错误，请重试');
            setAgentMessageComplete(agentId);
            setError(event.message ?? '连接失败');
            processingRef.current = false;
            break;
        }
      },
    ).catch((err) => {
      appendAgentChunk(agentId, '连接中断，请重试');
      setAgentMessageComplete(agentId);
      setError(err instanceof Error ? err.message : '连接失败');
      processingRef.current = false;
    });
  }, [chatHistory]);

  const sortedResults = useMemo(
    () => sortAdvisors(searchResults, sortBy),
    [searchResults, sortBy],
  );

  const hasChat = chatHistory.length > 0;

  // 左侧面板
  const leftPanel = (
    <div className={styles.leftPanel}>
      {hasChat && (
        <SortSelector value={sortBy} onChange={setSortBy} />
      )}

      <div className={styles.resultsArea}>
        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            closable
            style={{ margin: '12px 16px' }}
            onClose={() => setError(null)}
          />
        )}

        {!hasChat ? (
          <div className={styles.emptyState}>
            <Empty
              description={
                <span style={{ color: 'rgba(255,255,255,0.35)' }}>
                  开始对话以检索导师
                </span>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        ) : isStreaming && searchResults.length === 0 ? (
          <div className={styles.loadingState}>
            {[1, 2, 3].map((i) => (
              <div key={i} className={styles.skeletonCard}>
                <Skeleton active paragraph={{ rows: 3 }} />
              </div>
            ))}
          </div>
        ) : sortedResults.length === 0 ? (
          <div className={styles.emptyState}>
            <Empty
              description={
                <span style={{ color: 'rgba(255,255,255,0.35)' }}>
                  未找到匹配的导师，试试换个关键词？
                </span>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        ) : (
          <div className={styles.resultsList}>
            {sortedResults.map((advisor) => (
              <AdvisorCard
                key={advisor.id}
                advisor={advisor}
                compact={cardDensity === 'compact'}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className={styles.container}>
      <ResizableSplit left={leftPanel} right={<ChatWindow />} defaultRatio={0.45} ratio={splitRatio} onRatioChange={setSplitRatio} />
    </div>
  );
}

export default SearchPage;
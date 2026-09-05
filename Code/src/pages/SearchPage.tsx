import { useEffect, useRef, useMemo, useState } from 'react';
import { Empty, Skeleton, Alert, App } from 'antd';
import { Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useSearchStore } from '../stores/searchStore';
import { useMissionStore } from '../stores/missionStore';
import { useSettingsStore } from '../stores/settingsStore';
import { chatWithAgent } from '../services/agent';
import { recordSearch, recordChat } from '../services/user';
import { keepDisplayableAdvisors } from '../utils/mentorQualify';
import type { Advisor, AgentStage, SortBy } from '../types/search';
import SortSelector from '../components/SortSelector';
import AdvisorCard from '../components/AdvisorCard';
import ChatBubble from '../components/ChatBubble';
import { StageTimeline } from '../components/ChatBubble';
import SearchBar from '../components/SearchBar';
import AgentRunStrip from '../components/AgentRunStrip';
import styles from './SearchPage.module.css';

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
      sorted.sort((a, b) => (b.papers ?? 0) - (a.papers ?? 0));
      break;
    case 'department':
      sorted.sort((a, b) => a.department.localeCompare(b.department, 'zh'));
      break;
  }
  return sorted;
}

function SearchPage() {
  const { modal } = App.useApp();
  const navigate = useNavigate();
  const chatHistory = useSearchStore((s) => s.chatHistory);
  const searchResults = useSearchStore((s) => s.searchResults);
  const sortBy = useSearchStore((s) => s.sortBy);
  const isStreaming = useSearchStore((s) => s.isStreaming);
  const suggestedNextSkill = useSearchStore((s) => s.suggestedNextSkill);
  const pendingQuery = useSearchStore((s) => s.pendingQuery);
  const setSearchResults = useSearchStore((s) => s.setSearchResults);
  const setSortBy = useSearchStore((s) => s.setSortBy);
  const clearChat = useSearchStore((s) => s.clearChat);
  const appendAgentChunk = useSearchStore((s) => s.appendAgentChunk);
  const appendAgentStage = useSearchStore((s) => s.appendAgentStage);
  const appendAgentEvent = useSearchStore((s) => s.appendAgentEvent);
  const setAgentMessageComplete = useSearchStore((s) => s.setAgentMessageComplete);
  const setSuggestedNextSkill = useSearchStore((s) => s.setSuggestedNextSkill);
  const setWorkflowIdentity = useSearchStore((s) => s.setWorkflowIdentity);
  const ingestEvent = useMissionStore((s) => s.ingestEvent);
  const resetMission = useMissionStore((s) => s.reset);

  const defaultSort = useSettingsStore((s) => s.defaultSort);
  const cardDensity = useSettingsStore((s) => s.cardDensity);

  const [error, setError] = useState<string | null>(null);

  const liveStages: AgentStage[] = useMemo(() => {
    const last = [...chatHistory].reverse().find((m) => m.role === 'agent');
    return last?.stages ?? [];
  }, [chatHistory]);

  useEffect(() => {
    setSortBy(defaultSort as SortBy);
  }, []);

  // 云图 / 历史恢复的 pendingQuery：原 ChatWindow 消费，三栏后由本页接手
  useEffect(() => {
    if (!pendingQuery) return;
    if (useSearchStore.getState().isStreaming) return;
    useSearchStore.getState().setPendingQuery(null);
    useSearchStore.getState().addUserMessage(pendingQuery);
  }, [pendingQuery, isStreaming]);

  const processingRef = useRef(false);
  const searchRecordedRef = useRef(false);

  useEffect(() => {
    if (chatHistory.length < 2) return;

    const userMsg = chatHistory[chatHistory.length - 2];
    const agentMsg = chatHistory[chatHistory.length - 1];

    if (userMsg.role !== 'user' || agentMsg.role !== 'agent' || !agentMsg.isStreaming) return;
    if (processingRef.current) return;

    processingRef.current = true;
    searchRecordedRef.current = false;
    setError(null);
    setSuggestedNextSkill(null);
    resetMission();

    const agentId = agentMsg.id;
    const sessionId = useSearchStore.getState().sessionId;
    const { clarificationPending, activeTraceId, pendingUploadId } = useSearchStore.getState();
    useSearchStore.getState().setPendingUploadId(null);
    if (sessionId) {
      recordChat(sessionId, 'user', userMsg.content).catch(() => {});
    }

    (async () => {
      await chatWithAgent(
        userMsg.content,
        (event) => {
          if (event.trace_id || event.run_id || event.clarification_pending != null) {
            setWorkflowIdentity({
              traceId: event.trace_id,
              runId: event.run_id,
              clarificationPending: event.clarification_pending,
            });
          }
          switch (event.type) {
            case 'event':
              if (event.event) {
                appendAgentEvent(agentId, event.event);
                ingestEvent(event.event);
              }
              break;
            case 'stage':
              if (event.event_type) {
                appendAgentStage(agentId, {
                  event_type: event.event_type,
                  summary: event.summary || event.event_type,
                  sender: event.sender,
                  receiver: event.receiver,
                  timestamp: event.timestamp,
                  payload: event.payload,
                  evidence_refs: event.evidence_refs,
                });
              }
              break;
            case 'thinking':
              if (event.content) appendAgentChunk(agentId, event.content + '\n');
              break;
            case 'summary':
              if (event.content) appendAgentChunk(agentId, event.content);
              break;
            case 'result':
              if (event.response_kind === 'chat') {
                setSearchResults([]);
                setAgentMessageComplete(agentId, undefined, 'chat');
                break;
              }
              if (event.suggested_next_skill) {
                setSuggestedNextSkill(event.suggested_next_skill);
              }
              if (event.advisors) {
                const advisors = keepDisplayableAdvisors(event.advisors, event.threshold);
                setSearchResults(advisors);
                setAgentMessageComplete(agentId, advisors);
                if (!searchRecordedRef.current) {
                  searchRecordedRef.current = true;
                  recordSearch(userMsg.content, advisors.length, {
                    runId: event.run_id,
                    traceId: event.trace_id,
                  }).catch(() => {});
                }
              }
              break;
            case 'done':
              setAgentMessageComplete(agentId);
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
        {
          resumeTraceId: clarificationPending ? activeTraceId : null,
          uploadId: pendingUploadId,
        },
      );
    })().catch((err) => {
      appendAgentChunk(agentId, '连接中断，请重试');
      setAgentMessageComplete(agentId);
      setError(err instanceof Error ? err.message : '连接失败');
      processingRef.current = false;
    });
  }, [chatHistory]);

  const sortedResults = useMemo(
    () => keepDisplayableAdvisors(sortAdvisors(searchResults, sortBy)),
    [searchResults, sortBy],
  );
  const firstMatchedId = sortedResults[0]?.id;

  const hasChat = chatHistory.length > 0;
  const latestAgent = [...chatHistory].reverse().find((message) => message.role === 'agent');
  const isPlainChat = latestAgent?.responseKind === 'chat';

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

  return (
    <div className={styles.container}>
      <div className={styles.regionHeader}>
        <div>
          <div className="font-mono text-[11px] tracking-[0.18em] text-slate-400">01</div>
          <h1 className="mt-1 text-[22px] font-semibold tracking-tight text-slate-800">检索</h1>
        </div>
        <div className={styles.regionActions}>
          {hasChat && sortedResults.length > 0 && (
            <SortSelector value={sortBy} onChange={setSortBy} />
          )}
          {hasChat && (
            <button
              type="button"
              onClick={handleNewChat}
              disabled={isStreaming}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[13px] text-slate-500 hover:bg-slate-50 hover:text-slate-800 disabled:opacity-40"
            >
              <Plus size={14} strokeWidth={1.5} className="text-slate-600" />
              新对话
            </button>
          )}
        </div>
      </div>

      <AgentRunStrip />

      <div className={styles.workspaceBody}>
        {error && (
          <Alert
            message={error}
            type="error"
            showIcon
            closable
            style={{ margin: '0 0 12px' }}
            onClose={() => setError(null)}
          />
        )}

        {suggestedNextSkill === 'paper_qa' && (
          <Alert
            className={styles.nextSkillBanner}
            type="info"
            showIcon
            message="建议下一步：阅读已匹配导师的论文"
            description="已有匹配导师、尚无阅读记录。打开详情页点击「阅读其论文」。"
            action={
              firstMatchedId ? (
                <a
                  href={`/advisor/${encodeURIComponent(firstMatchedId)}`}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(`/advisor/${encodeURIComponent(firstMatchedId)}`);
                  }}
                >
                  去阅读
                </a>
              ) : null
            }
          />
        )}

          {hasChat && (
            <div className={styles.chatStrip}>
            {chatHistory.map((msg) => (
              <ChatBubble key={msg.id} message={msg} />
            ))}
            {isStreaming && liveStages.length > 0 && (
              <div className={styles.liveTimeline}>
                <div className={styles.liveTimelineTitle}>多智能体过程</div>
                <StageTimeline stages={liveStages} />
              </div>
            )}
          </div>
        )}

        {hasChat && !isPlainChat && (
          <>
            {isStreaming && searchResults.length === 0 ? (
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
                  description={<span className="text-stone-400">没有达到相关阈值的导师</span>}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            ) : (
              <div className={styles.resultsList}>
                {sortedResults.map((advisor, index) => (
                  <AdvisorCard
                    key={advisor.id}
                    advisor={advisor}
                    compact={cardDensity === 'compact'}
                    featured={index === 0}
                  />
                ))}
              </div>
            )}
          </>
        )}

        {!hasChat && (
          <div className={styles.emptyState}>
            <Empty
              description={
                <span className="text-stone-400">
                  描述你想找的导师方向（当前检索库 721 位 / 1747 条证据）
                </span>
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        )}
      </div>

      <SearchBar />
    </div>
  );
}

export default SearchPage;

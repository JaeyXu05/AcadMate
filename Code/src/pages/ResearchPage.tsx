import { useEffect, useMemo, useState } from 'react';
import { useAutoScroll } from '../utils/useAutoScroll';
import { Button, Empty, Input, Modal, Select, Spin, message } from 'antd';
import { BookOpen, Check, ChevronRight, FileText, MessageCircle, Plus, Search as SearchIcon, Send, Target } from 'lucide-react';
import * as conversationsApi from '../services/conversations';
import type { Conversation, ConversationMessage, ConversationSummary } from '../services/conversations';
import * as researchApi from '../services/research';
import type { ResearchProject } from '../services/research';
import * as papersApi from '../services/papers';
import type { PaperSearchCandidate } from '../services/papers';
import { apiErrorMessage } from '../services/axios';
import { useMissionStore } from '../stores/missionStore';
import type { RuntimeEvent } from '../types/search';
import styles from './ResearchPage.module.css';

function extractPaperQuery(text: string): string | null {
  const trimmed = text.trim().replace(/[。.!！?？]+$/g, '');
  if (!trimmed) return null;
  const patterns = [
    /(?:请|帮我)?(?:检索|搜索|查找|搜|查|找)\s*(?:一下)?\s*[「『《“"']?(.+?)[」』》”"']?\s*(?:这篇|这篇的)?\s*论文/,
    /(?:请|帮我)?(?:检索|搜索|查找)\s*(?:一下)?\s*(.+)$/,
    /(?:论文|paper)\s*[:：]\s*(.+)$/i,
  ];
  for (const pattern of patterns) {
    const matched = trimmed.match(pattern);
    const query = matched?.[1]?.trim().replace(/^[\s《»「」『』"'“”]+|[\s《»「」『』"'“”]+$/g, '');
    if (query && query.length >= 2 && query.length <= 200) return query;
  }
  return null;
}

function formatPaperCandidates(result: papersApi.PaperSearchResponse): string {
  if (!result.candidates?.length) {
    return result.warnings?.[0] || `没有找到与「${result.query}」匹配的论文。可以换个完整标题、DOI 或 arXiv id 再试。`;
  }
  const lines = result.candidates.slice(0, 8).map((item, index) => {
    const meta = [item.year, item.source, item.arxiv_id || item.doi].filter(Boolean).join(' · ');
    return `${index + 1}. ${item.title}${meta ? `（${meta}）` : ''}`;
  });
  return `已从 ${result.source} 检索到 ${result.candidates.length} 篇候选，并填入右侧「论文检索」。点选一篇后可点「分析当前论文」。\n\n${lines.join('\n')}`;
}

function emitResearchEvent(
  ingestEvent: (event: RuntimeEvent) => void,
  eventType: string,
  stage: RuntimeEvent['stage'],
  message: string,
  payload?: Record<string, unknown>,
): void {
  ingestEvent({
    event_type: eventType,
    stage,
    sender: 'research_workbench',
    receiver: 'user',
    timestamp: new Date().toISOString(),
    message,
    payload,
  });
}

function ResearchPage() {
  const [projects, setProjects] = useState<ResearchProject[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedConversation, setSelectedConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [goalDraft, setGoalDraft] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [sending, setSending] = useState(false);
  const [projectModal, setProjectModal] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectGoal, setProjectGoal] = useState('');
  const [paperQuery, setPaperQuery] = useState('');
  const [paperSource, setPaperSource] = useState<'local' | 'arxiv' | 'openalex'>('openalex');
  const [paperCandidates, setPaperCandidates] = useState<PaperSearchCandidate[]>([]);
  const [paperSessionId, setPaperSessionId] = useState<number | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(null);
  const [selectedPaperTitle, setSelectedPaperTitle] = useState('');
  const [searchingPapers, setSearchingPapers] = useState(false);
  const ingestEvent = useMissionStore((state) => state.ingestEvent);
  const resetMission = useMissionStore((state) => state.reset);
  const { scrollerRef: messagesRef, endRef: messagesEndRef, onScroll: onMessagesScroll } = useAutoScroll([messages, sending, paperCandidates]);
  const { scrollerRef: contextRef, endRef: contextEndRef, onScroll: onContextScroll } = useAutoScroll([paperCandidates, paperQuery, searchingPapers]);

  const selectedProject = useMemo(
    () => projects.find((item) => item.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await researchApi.listProjects();
        if (cancelled) return;
        setProjects(items);
        setSelectedProjectId(items[0]?.id ?? null);
      } catch (error: unknown) {
        if (!cancelled) message.error(apiErrorMessage(error, '科研项目加载失败'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (loading) return;
    let cancelled = false;
    (async () => {
      try {
        const items = await conversationsApi.listConversations({ surface: 'research', projectId: selectedProjectId ?? undefined });
        if (!cancelled) {
          setConversations(items);
          setSelectedConversation(null);
          setMessages([]);
          setSelectedPaperId(null);
          setSelectedPaperTitle('');
          setPaperCandidates([]);
          setPaperSessionId(null);
        }
      } catch (error: unknown) {
        if (!cancelled) message.error(apiErrorMessage(error, '科研会话加载失败'));
      }
    })();
    return () => { cancelled = true; };
  }, [loading, selectedProjectId]);

  const openConversation = async (item: ConversationSummary) => {
    setLoadingConversation(true);
    try {
      const conversation = await conversationsApi.getConversation(item.id);
      setSelectedConversation(conversation);
      setMessages(conversation.messages || []);
      setGoalDraft('');
      const metadata = conversation.metadata || {};
      const activePaperId = Number(metadata.active_paper_id);
      setSelectedPaperId(Number.isInteger(activePaperId) && activePaperId > 0 ? activePaperId : null);
      setSelectedPaperTitle(typeof metadata.active_paper_title === 'string' ? metadata.active_paper_title : '');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '会话加载失败'));
    } finally {
      setLoadingConversation(false);
    }
  };

  const createProject = async () => {
    if (!projectName.trim()) return;
    try {
      const project = await researchApi.createProject({ name: projectName.trim(), goal: projectGoal.trim() });
      setProjects((current) => [project, ...current]);
      setSelectedProjectId(project.id);
      setProjectName('');
      setProjectGoal('');
      setProjectModal(false);
      message.success('科研项目已创建');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '科研项目创建失败'));
    }
  };

  const createConversation = async () => {
    try {
      const conversation = await conversationsApi.createConversation({
        surface: 'research',
        projectId: selectedProjectId ?? undefined,
      });
      setConversations((current) => [conversation, ...current]);
      setSelectedConversation(conversation);
      setMessages([]);
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '新建科研会话失败'));
    }
  };

  const saveGoal = async () => {
    if (!selectedConversation || !goalDraft.trim()) return;
    try {
      const goal = await conversationsApi.createGoal(selectedConversation.id, { title: goalDraft.trim() });
      setSelectedConversation((current) => current ? {
        ...current,
        active_goal: goal,
        goals: [goal, ...current.goals.filter((item) => item.id !== goal.id)],
        active_goal_id: goal.id,
      } : current);
      setGoalDraft('');
      message.success('当前目标已更新');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '目标更新失败'));
    }
  };

  const sendText = async (input: string) => {
    const text = input.trim();
    if (!text || sending) return;
    setDraft('');
    setSending(true);
    const paperQueryFromChat = extractPaperQuery(text);
    let conversation = selectedConversation;
    try {
      if (!conversation) {
        conversation = await conversationsApi.createConversation({
          surface: 'research',
          title: text.slice(0, 36),
          projectId: selectedProjectId ?? undefined,
        });
        setSelectedConversation(conversation);
        setConversations((current) => [conversation!, ...current]);
      }
      const userMessage: ConversationMessage = {
        id: -Date.now(), role: 'user', content: text, created_at: new Date().toISOString(),
      };
      const assistantId = -Date.now() - 1;
      setMessages((current) => [...current, userMessage, {
        id: assistantId,
        role: 'assistant',
        content: paperQueryFromChat ? '正在检索论文…' : '',
        created_at: new Date().toISOString(),
      }]);
      if (paperQueryFromChat) {
        resetMission();
        emitResearchEvent(ingestEvent, 'WORKFLOW_CREATED', 'input_understanding', '已收到论文检索请求');
        emitResearchEvent(ingestEvent, 'PLAN_READY', 'planning', '准备检索论文', {
          steps: [
            { step_id: 'input_understanding', agent_name: 'research_workbench' },
            { step_id: 'mentor_research', agent_name: 'paper_search' },
            { step_id: 'result_composer', agent_name: 'research_workbench' },
          ],
        });
        setPaperQuery(paperQueryFromChat);
        void searchPapers(paperQueryFromChat).then((result) => {
          if (!result) return;
          setMessages((current) => current.map((item) => (
            item.id === assistantId && (item.content === '正在检索论文…' || !item.content.trim())
              ? { ...item, content: formatPaperCandidates(result) }
              : item
          )));
        });
      }
      await conversationsApi.streamConversationMessage(conversation.id, text, (event) => {
        if (event.type === 'agent_chunk' && event.message) {
          setMessages((current) => current.map((item) => {
            if (item.id !== assistantId) return item;
            const previous = item.content === '正在检索论文…' ? '' : item.content;
            return { ...item, content: previous + event.message };
          }));
        }
        if (event.type === 'run_completed' && event.message) {
          setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, content: event.message! } : item));
          emitResearchEvent(ingestEvent, 'WORKFLOW_COMPLETED', 'completed', '科研助手已完成回复');
        }
        if (event.type === 'run_failed' && event.error) {
          setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, content: `这次处理没有完成：${event.error}` } : item));
          emitResearchEvent(ingestEvent, 'WORKFLOW_FAILED', 'failed', event.error);
        }
        if (event.type === 'run_waiting_for_user') {
          setMessages((current) => current.map((item) => item.id === assistantId ? {
            ...item,
            content: item.content.trim() && item.content !== '正在检索论文…'
              ? item.content
              : '需要你确认后才能继续。请在右侧论文检索中选择一篇，或直接告诉我选哪一篇。',
          } : item));
        }
      }, { activePaperId: selectedPaperId ?? undefined, activePaperTitle: selectedPaperTitle });
      const refreshed = await conversationsApi.getConversation(conversation.id);
      setSelectedConversation(refreshed);
      const serverMessages = refreshed.messages || [];
      setMessages((current) => {
        const local = current.find((item) => item.id === assistantId && item.content.trim() && item.content !== '正在检索论文…');
        const lastServer = [...serverMessages].reverse().find((item) => item.role === 'assistant' && item.content.trim());
        if (local && lastServer && local.content.length > lastServer.content.length) {
          return serverMessages.map((item) => item.id === lastServer.id ? { ...item, content: local.content } : item);
        }
        if (local && !lastServer) return [...serverMessages, { ...local, id: Date.now() }];
        return serverMessages.length ? serverMessages : current;
      });
      setConversations((current) => [refreshed, ...current.filter((item) => item.id !== refreshed.id)]);
    } catch (error: unknown) {
      setMessages((current) => [...current, { id: -Date.now(), role: 'assistant', content: apiErrorMessage(error, '科研 Agent 暂时不可用，请稍后重试'), created_at: new Date().toISOString() }]);
      emitResearchEvent(ingestEvent, 'WORKFLOW_FAILED', 'failed', apiErrorMessage(error, '科研 Agent 暂时不可用'));
    } finally {
      setSending(false);
    }
  };

  const send = () => {
    const text = draft.trim();
    if (text) void sendText(text);
  };

  const searchPapers = async (overrideQuery?: string, overrideSource?: 'local' | 'arxiv' | 'openalex'): Promise<papersApi.PaperSearchResponse | null> => {
    const query = (overrideQuery ?? paperQuery).trim();
    const source = overrideSource ?? paperSource;
    if (!query || searchingPapers) return null;
    setSearchingPapers(true);
    emitResearchEvent(ingestEvent, 'RESEARCH_STARTED', 'mentor_research', `正在从 ${source} 检索「${query}」`);
    try {
      let result = await papersApi.searchPapers({ query, source, limit: 8 });
      if (!result.candidates?.length && source !== 'local') {
        const alt = source === 'arxiv' ? 'openalex' : 'arxiv';
        const second = await papersApi.searchPapers({ query, source: alt, limit: 8 });
        if (second.candidates?.length) {
          setPaperSource(alt);
          result = second;
        }
      }
      setPaperSessionId(result.search_session_id);
      setPaperCandidates(result.candidates || []);
      if (!result.candidates?.length) {
        message.info(result.warnings?.[0] || '暂未找到候选论文');
        emitResearchEvent(ingestEvent, 'NO_QUALIFIED_MATCH', 'mentor_research', result.warnings?.[0] || '暂未找到候选论文');
      } else {
        emitResearchEvent(ingestEvent, 'RESEARCH_DONE', 'mentor_research', `找到 ${result.candidates.length} 篇候选论文`);
        emitResearchEvent(ingestEvent, 'WORKFLOW_COMPLETED', 'completed', `论文检索完成（${result.source}）`, {
          quality_status: 'PASS',
          review_decision: {
            status: 'PASS',
            reviewer_summary: `从 ${result.source} 找到 ${result.candidates.length} 篇候选论文`,
          },
          evidence_ledger: result.candidates.slice(0, 8).map((item) => ({
            evidence_id: `paper:${item.id}`,
            candidate_id: String(item.id),
            source_type: item.source,
            title: item.title,
            source_uri: item.landing_page_url || item.pdf_url || undefined,
            query_relevance: 1,
            support_type: 'DIRECT',
            source_level: 'L3',
            freshness: 'current',
          })),
          match_results: result.candidates.slice(0, 8).map((item, index) => ({
            candidate_id: String(item.id),
            total_score: 80,
            match_type: 'DIRECT',
            ranking_position: index + 1,
            rationale: [item.title],
          })),
        });
      }
      return result;
    } catch (error: unknown) {
      const detail = apiErrorMessage(error, '论文检索失败');
      message.error(detail);
      emitResearchEvent(ingestEvent, 'WORKFLOW_FAILED', 'failed', detail);
      return {
        search_session_id: 0,
        source,
        mode: 'keyword',
        query,
        query_used: query,
        status: 'failed',
        warnings: [detail],
        candidates: [],
      };
    } finally {
      setSearchingPapers(false);
    }
  };

  const selectPaper = async (candidate: PaperSearchCandidate) => {
    if (!paperSessionId) return;
    try {
      const selected = await papersApi.confirmPaperCandidate(paperSessionId, candidate.id);
      if (!selected.paper_id) throw new Error('PAPERCLAW 未返回论文编号');
      setSelectedPaperId(selected.paper_id);
      setSelectedPaperTitle(selected.title || candidate.title);
      setPaperCandidates((items) => items.map((item) => item.id === candidate.id ? { ...item, paper_id: selected.paper_id } : item));
      message.success('已加入当前科研会话，可直接说“分析当前论文”');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '论文选择失败'));
    }
  };

  const analyzeCurrentPaper = () => {
    if (!selectedPaperId) {
      message.info('请先检索并选择一篇论文');
      return;
    }
    void sendText('请分析当前选中的论文：概括研究问题、方法、主要发现、局限与可复现实验建议；所有结论请绑定论文内容。');
  };

  if (loading) return <div className={styles.loading}><Spin /></div>;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <div className={styles.kicker}>09 · RESEARCH</div>
          <h1>科研工作台</h1>
          <p>从日常讨论开始，需要时再查论文、读 PDF、整理证据和计划。</p>
        </div>
        <Button icon={<Plus size={15} />} onClick={() => setProjectModal(true)}>新建项目</Button>
      </header>

      <div className={styles.workspace}>
        <aside className={styles.projects}>
          <div className={styles.sectionTitle}><BookOpen size={14} /> 科研项目</div>
          {projects.length === 0 ? (
            <button className={styles.emptyAction} onClick={() => setProjectModal(true)}>创建第一个科研项目</button>
          ) : projects.map((project) => (
            <button key={project.id} className={`${styles.projectItem} ${project.id === selectedProjectId ? styles.selected : ''}`} onClick={() => setSelectedProjectId(project.id)}>
              <span>{project.name}</span><small>{project.status}</small>
            </button>
          ))}
          <div className={styles.sectionTitle}><MessageCircle size={14} /> 最近会话</div>
          <button className={styles.newConversation} onClick={createConversation}><Plus size={14} /> 新会话</button>
          {conversations.map((item) => (
            <button key={item.id} className={`${styles.conversationItem} ${item.id === selectedConversation?.id ? styles.selected : ''}`} onClick={() => openConversation(item)}>
              <span>{item.title}</span><small>{item.updated_at?.slice(0, 10)}</small>
            </button>
          ))}
        </aside>

        <main className={styles.chat}>
          <div className={styles.chatHeader}>
            <div>
              <span className={styles.surfaceLabel}>科研对话</span>
              <h2>{selectedConversation?.title || '还没有打开会话'}</h2>
            </div>
            {selectedProject && <Select size="small" value={selectedProject.id} onChange={setSelectedProjectId} options={projects.map((item) => ({ label: item.name, value: item.id }))} />}
          </div>
          <div className={styles.goalBar}>
            <Target size={15} />
            <span>{selectedConversation?.active_goal?.title || selectedProject?.goal || '当前还没有设定目标，可以直接聊天'}</span>
            {selectedConversation && <Input size="small" value={goalDraft} onChange={(event) => setGoalDraft(event.target.value)} onPressEnter={saveGoal} placeholder="输入新目标并回车" />}
            {selectedConversation && goalDraft.trim() && <Button size="small" type="text" icon={<Check size={14} />} onClick={saveGoal} />}
          </div>
          <div ref={messagesRef} className={styles.messages} onScroll={onMessagesScroll}>
            {loadingConversation ? <Spin /> : messages.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="可以先说说你最近在研究什么，也可以直接说“查几篇相关论文”" />
            ) : messages.map((item) => (
              <div key={item.id} className={`${styles.message} ${item.role === 'user' ? styles.userMessage : styles.agentMessage}`}>
                <div className={styles.messageRole}>{item.role === 'user' ? '你' : '科研助手'}</div>
                <div className={styles.messageContent}>{item.content || (sending ? '正在思考…' : '')}</div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
          <div className={styles.composer}>
            <Input.TextArea value={draft} onChange={(event) => setDraft(event.target.value)} onPressEnter={(event) => { if (!event.shiftKey) { event.preventDefault(); void send(); } }} autoSize={{ minRows: 2, maxRows: 6 }} disabled={sending} placeholder="和科研助手聊聊，普通问题也可以…" />
            <Button type="primary" icon={<Send size={15} />} loading={sending} disabled={!draft.trim()} onClick={() => void send()}>发送</Button>
          </div>
        </main>

        <aside ref={contextRef} className={styles.context} onScroll={onContextScroll}>
          <div className={styles.contextTitle}>当前上下文</div>
          <div className={styles.contextCard}><Target size={15} /><div><strong>目标</strong><span>{selectedConversation?.active_goal?.title || selectedProject?.goal || '未设置'}</span></div><ChevronRight size={14} /></div>
          <div className={`${styles.contextCard} ${styles.paperCard}`}><FileText size={15} /><div><strong>论文检索</strong><span>{selectedPaperId ? `当前：${selectedPaperTitle}` : '从 PAPERCLAW 检索并选择论文'}</span></div></div>
          <div className={styles.paperTools}>
            <div className={styles.paperSearchRow}>
              <Input size="small" value={paperQuery} onChange={(event) => setPaperQuery(event.target.value)} onPressEnter={() => void searchPapers()} placeholder="输入标题、主题或 DOI" />
              <Button size="small" type="primary" icon={<SearchIcon size={13} />} loading={searchingPapers} onClick={() => void searchPapers()} />
            </div>
            <Select size="small" value={paperSource} onChange={setPaperSource} options={[{ label: 'OpenAlex', value: 'openalex' }, { label: 'arXiv', value: 'arxiv' }, { label: '本地目录', value: 'local' }]} />
            {paperCandidates.length > 0 && <div className={styles.paperResults}>
              {paperCandidates.map((candidate) => (
                <div key={candidate.id} className={`${styles.paperResult} ${candidate.paper_id === selectedPaperId ? styles.paperSelected : ''}`}>
                  <div className={styles.paperResultTitle}>{candidate.title}</div>
                  <div className={styles.paperResultMeta}>{candidate.year || '年份未知'} · {candidate.source}</div>
                  <Button size="small" type={candidate.paper_id === selectedPaperId ? 'primary' : 'text'} onClick={() => void selectPaper(candidate)}>{candidate.paper_id === selectedPaperId ? '已选择' : '选择'}</Button>
                </div>
              ))}
            </div>}
            <Button block size="small" icon={<FileText size={13} />} onClick={analyzeCurrentPaper} disabled={!selectedPaperId}>分析当前论文</Button>
          </div>
          <div className={styles.contextCard}><MessageCircle size={15} /><div><strong>使用方式</strong><span>需要查找、分析或生成报告时直接告诉我</span></div></div>
          <div ref={contextEndRef} />
        </aside>
      </div>

      <Modal open={projectModal} title="新建科研项目" okText="创建" cancelText="取消" onOk={() => void createProject()} onCancel={() => setProjectModal(false)}>
        <Input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="例如：生成式推荐系统综述" className="mb-3" />
        <Input.TextArea value={projectGoal} onChange={(event) => setProjectGoal(event.target.value)} placeholder="可选：这个项目希望解决什么问题？" autoSize={{ minRows: 3, maxRows: 6 }} />
      </Modal>
    </div>
  );
}

export default ResearchPage;

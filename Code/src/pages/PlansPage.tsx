import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Empty, InputNumber, Modal, Popconfirm, Progress, Select, Spin, Switch, message, notification } from 'antd';
import { Sparkles, Trash2, Pencil, Plus, CalendarClock } from 'lucide-react';
import * as plansApi from '../services/plans';
import type { PlanCoachEvent, PlanCoachJob, PlanCoachResult, PlanInput, PlanPriority, PlanReminder, PlanStatus, ResearchPlan } from '../services/plans';
import { apiErrorMessage } from '../services/axios';
import styles from './ProductivityPage.module.css';

const emptyPlan: PlanInput = {
  parent_plan_id: null, title: '', description: '', deliverable: '', acceptance_criteria: [], sequence: null, status: 'todo', priority: 'medium', start_at: null,
  due_at: null, estimated_minutes: 60, actual_minutes: 0, execution_notes: '', reminder_at: null, email_reminder: 0,
};

const priorityLabel: Record<PlanPriority, string> = { high: '高优先级', medium: '中优先级', low: '低优先级' };

function toLocalInput(value?: string | null): string {
  return value ? value.replace(' ', 'T').slice(0, 16) : '';
}

function PlansPage() {
  const [items, setItems] = useState<ResearchPlan[]>([]);
  const [coachResult, setCoachResult] = useState<PlanCoachResult | null>(null);
  const [coachJob, setCoachJob] = useState<PlanCoachJob | null>(null);
  const [coachEvents, setCoachEvents] = useState<PlanCoachEvent[]>([]);
  const [reminders, setReminders] = useState<PlanReminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [coaching, setCoaching] = useState(false);
  const [applying, setApplying] = useState(false);
  const [editing, setEditing] = useState<ResearchPlan | null>(null);
  const [draft, setDraft] = useState<PlanInput>(emptyPlan);
  const [open, setOpen] = useState(false);
  const [completionPlan, setCompletionPlan] = useState<ResearchPlan | null>(null);
  const [completionNotes, setCompletionNotes] = useState('');
  const [completionMinutes, setCompletionMinutes] = useState(0);
  const [completing, setCompleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [plans, planReminders] = await Promise.all([plansApi.listPlans(), plansApi.getPlanReminders()]);
      setItems(plans);
      setReminders(planReminders);
      setLoadError(null);
    } catch (error: unknown) {
      const text = apiErrorMessage(error, '计划加载失败');
      setLoadError(text);
      message.error(text);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [rows, planReminders] = await Promise.all([plansApi.listPlans(), plansApi.getPlanReminders()]);
        if (!cancelled) {
          setItems(rows);
          setReminders(planReminders);
          setLoadError(null);
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const text = apiErrorMessage(error, '计划加载失败');
          setLoadError(text);
          message.error(text);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const showEditor = (item?: ResearchPlan) => {
    setEditing(item || null);
    setDraft(item ? {
      title: item.title, description: item.description, status: item.status, priority: item.priority,
      parent_plan_id: item.parent_plan_id || null, deliverable: item.deliverable || '', acceptance_criteria: item.acceptance_criteria || [], sequence: item.sequence || null,
      start_at: item.start_at, due_at: item.due_at, estimated_minutes: item.estimated_minutes,
      actual_minutes: item.actual_minutes, execution_notes: item.execution_notes || '', reminder_at: item.reminder_at, email_reminder: item.email_reminder,
    } : emptyPlan);
    setOpen(true);
  };

  const save = async () => {
    if (!draft.title.trim()) { message.warning('请填写计划标题'); return; }
    try {
      if (editing) await plansApi.updatePlan(editing.id, draft); else await plansApi.createPlan(draft);
      setOpen(false);
      await load();
      message.success('计划已保存');
    } catch (error: any) { message.error(error?.response?.data?.message || '计划保存失败'); }
  };

  const updateStatus = async (item: ResearchPlan, status: PlanStatus) => {
    if (status === 'done' && item.status !== 'done') {
      setCompletionPlan(item);
      setCompletionNotes(item.execution_notes || '');
      setCompletionMinutes(item.actual_minutes || item.estimated_minutes || 30);
      return;
    }
    await plansApi.updatePlan(item.id, { ...item, status });
    await load();
  };

  const submitCompletion = async () => {
    if (!completionPlan) return;
    if (completionNotes.trim().length < 4) { message.warning('请写下实际完成结果、产出或遇到的问题'); return; }
    if (!completionMinutes || completionMinutes < 1) { message.warning('请填写实际投入分钟数'); return; }
    setCompleting(true);
    try {
      await plansApi.completePlan(completionPlan.id, { execution_notes: completionNotes.trim(), actual_minutes: completionMinutes });
      setCompletionPlan(null);
      await load();
      message.success('完成反馈已记录，后续报告和 AI 规划会使用这条信息');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '完成反馈保存失败'));
    } finally { setCompleting(false); }
  };

  const coach = async () => {
    setCoaching(true);
    try {
      const job = await plansApi.getPlanSuggestions();
      setCoachJob(job); setCoachEvents(job.events || []); setCoachResult(job.artifact || null);
    }
    catch (error: any) { message.error(error?.response?.data?.message || 'AI 建议生成失败'); }
    finally { setCoaching(false); }
  };

  useEffect(() => {
    if (!coachJob?.run_id || !['queued', 'pending', 'running'].includes(coachJob.status)) return undefined;
    let cancelled = false;
    let lastSequence = Math.max(0, ...coachEvents.map((event) => Number(event.sequence || 0)));
    const poll = async () => {
      try {
        const [job, events] = await Promise.all([plansApi.getPlanSuggestionJob(coachJob.run_id!), plansApi.getPlanSuggestionEvents(coachJob.run_id!, lastSequence)]);
        if (cancelled) return;
        if (events.length) { lastSequence = Math.max(lastSequence, ...events.map((event) => Number(event.sequence || 0))); setCoachEvents((current) => [...current, ...events]); }
        setCoachJob(job);
        if (job.artifact) setCoachResult(job.artifact);
      } catch (error) { if (!cancelled) message.error(apiErrorMessage(error, '计划任务状态读取失败')); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1300);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [coachJob?.run_id, coachJob?.status]);

  const cancelCoach = async () => {
    if (!coachJob?.run_id) return;
    try { const job = await plansApi.cancelPlanSuggestion(coachJob.run_id); setCoachJob(job); message.info('已请求取消计划生成'); }
    catch (error) { message.error(apiErrorMessage(error, '计划任务取消失败')); }
  };

  const applyDrafts = async (drafts: NonNullable<PlanCoachResult['plan_drafts']>) => {
    if (!drafts.length) return;
    setApplying(true);
    try {
      const created = await plansApi.applyPlanDrafts(drafts);
      await load();
      message.success(`已将 ${created.length} 个阶段任务加入科研计划，并保留提醒设置`);
    } catch (error: any) {
      message.error(error?.response?.data?.message || '计划拆解应用失败');
    } finally { setApplying(false); }
  };

  useEffect(() => {
    const due = reminders.filter((item) => item.state === 'due');
    if (due.length) notification.info({ key: 'plan-reminders', message: '科研计划提醒', description: due.map((item) => `「${item.title}」已到提醒时间`).join('；'), duration: 8 });
  }, [reminders]);

  return (
    <div className={`${styles.container} pt-12`}>
      <h2 className={styles.title}><CalendarClock size={16} strokeWidth={1.5} className="text-slate-600" /> 科研计划</h2>
      <p className={styles.subtitle}>用可验收的交付物规划研究工作；AI 仅基于已记录历史提出建议，不虚构进展。</p>
      <div className={styles.toolbar}>
        <Button icon={<Sparkles size={14} strokeWidth={1.5} className="text-slate-600" />} loading={coaching} disabled={Boolean(coachJob?.run_id && ['queued', 'pending', 'running'].includes(coachJob.status))} onClick={coach}>AI 个性化建议</Button>
        <Button type="primary" icon={<Plus size={14} strokeWidth={1.5} />} onClick={() => showEditor()}>新增计划</Button>
      </div>
      {reminders.length > 0 && <Alert className={styles.reminderAlert} type={reminders.some((item) => item.state === 'due') ? 'warning' : 'info'} showIcon message={reminders.some((item) => item.state === 'due') ? '有科研计划已到提醒时间' : '未来 24 小时内有科研计划提醒'} description={reminders.map((item) => `「${item.title}」${item.state === 'due' ? '现在需要处理' : `提醒时间：${item.reminder_at}`}${item.email_reminder ? '（已启用邮箱提醒）' : ''}`).join('；')} />}
      {coachJob?.run_id && ['queued', 'pending', 'running'].includes(coachJob.status) && <section className={styles.suggestionCard}>
        {(() => { const latest = coachEvents[coachEvents.length - 1]?.payload; const percent = Math.max(5, Math.min(95, Number(latest?.progress || 8))); return <><div className={styles.coachHeader}><div><h3>正在深度规划科研计划</h3><p>{latest?.message || '正在准备个人科研历史与当前计划。'}</p></div><Button size="small" onClick={() => void cancelCoach()}>取消</Button></div><Progress percent={percent} status="active" /><p className={styles.coachBasis}>仅显示任务阶段，不展示模型内部推理；本次输入已使用个人 Harness 历史摘要。</p></>; })()}
      </section>}
      {coachResult && <section className={styles.suggestionCard}>
        <div className={styles.coachHeader}><div><h3>AI 个性化计划拆解</h3><p>{coachResult.planning_summary || '已生成计划建议。'}</p></div>{coachResult.generation?.status === 'fallback' && <span className={styles.warning}>当前为降级规划，请复核后应用。</span>}</div>
        {coachResult.capacity_assessment && <div className={styles.coachAssessment}><b>时间与范围判断：</b>{coachResult.capacity_assessment}</div>}
        {!!coachResult.personalization_basis?.length && <div className={styles.coachBasis}>个性化依据：{coachResult.personalization_basis.join('；')}</div>}
        {!!coachResult.risks?.length && <Alert className={styles.coachRisk} type="warning" showIcon message="需要留意" description={coachResult.risks.join('；')} />}
        {!!coachResult.plan_drafts?.length && <div className={styles.milestoneList}>{coachResult.plan_drafts.map((draft, index) => <article key={`${draft.title}-${index}`} className={styles.milestoneCard}>
          <div className={styles.planHeader}><h4>第 {draft.sequence || index + 1} 阶段：{draft.title}</h4><span className={`${styles.priority} ${styles[draft.priority]}`}>{priorityLabel[draft.priority]}</span></div>
          {draft.deliverable && <p><b>交付物：</b>{draft.deliverable}</p>}
          {!!draft.acceptance_criteria?.length && <p><b>验收标准：</b>{draft.acceptance_criteria.join('；')}</p>}
          <div className={styles.planMeta}>开始：{draft.start_at || '待确认'} · 截止：{draft.due_at || '待确认'} · 预计 {draft.estimated_minutes} 分钟 · 提醒：{draft.reminder_at || '待确认'}</div>
          <Popconfirm title="将这个阶段加入正式科研计划？" onConfirm={() => void applyDrafts([draft])}><Button size="small" loading={applying}>应用此阶段</Button></Popconfirm>
        </article>)}</div>}
        {!!coachResult.plan_drafts?.length && <Popconfirm title="将全部阶段任务写入科研计划？原始总计划不会被自动删除或完成。" onConfirm={() => void applyDrafts(coachResult.plan_drafts || [])}><Button type="primary" loading={applying}>应用全部拆解</Button></Popconfirm>}
      </section>}
      {loading ? <div className={styles.loading}><Spin /></div> : loadError ? <Empty description={loadError} /> : items.length === 0 ? <Empty description="暂无计划" /> : (
        <div className={styles.planGrid}>
          {items.map((item) => <article className={styles.planCard} key={item.id}>
            <div className={styles.planHeader}><h3>{item.sequence ? `阶段 ${item.sequence} · ` : ''}{item.title}</h3><span className={`${styles.priority} ${styles[item.priority]}`}>{priorityLabel[item.priority]}</span></div>
            <p>{item.description || '未填写说明'}</p>
            {item.deliverable && <div className={styles.planDetail}><b>交付物：</b>{item.deliverable}</div>}
            {!!item.acceptance_criteria?.length && <div className={styles.planDetail}><b>验收：</b>{item.acceptance_criteria.join('；')}</div>}
            <div className={styles.planMeta}>开始：{item.start_at || '未设置'} · 截止：{item.due_at || '未设置'} · 预计 {item.estimated_minutes} 分钟</div>
            {item.status === 'done' && <div className={styles.completionFeedback}><b>完成反馈：</b>{item.execution_notes || '未补充实际成果说明'}<span>实际投入 {item.actual_minutes || 0} 分钟</span></div>}
            {item.reminder_at && <div className={styles.planMeta}>提醒：{item.reminder_at}{item.email_reminder ? '（邮箱提醒已启用）' : ''}</div>}
            <div className={styles.planActions}>
              <Select value={item.status} size="small" onChange={(value) => void updateStatus(item, value)} options={[{ value: 'todo', label: '待办' }, { value: 'doing', label: '进行中' }, { value: 'done', label: '已完成' }, { value: 'cancelled', label: '已取消' }]} />
              {item.status !== 'done' && <Button size="small" onClick={() => { setCompletionPlan(item); setCompletionNotes(item.execution_notes || ''); setCompletionMinutes(item.actual_minutes || item.estimated_minutes || 30); }}>完成并反馈</Button>}
              <Button size="small" icon={<Pencil size={14} strokeWidth={1.5} className="text-slate-600" />} onClick={() => showEditor(item)}>编辑</Button>
              <Popconfirm title="确定删除该计划？" onConfirm={async () => { await plansApi.deletePlan(item.id); await load(); }}><Button danger size="small" icon={<Trash2 size={14} strokeWidth={1.5} className="text-slate-600" />} /></Popconfirm>
            </div>
          </article>)}
        </div>
      )}

      <Modal title={editing ? '编辑科研计划' : '新增科研计划'} open={open} onOk={save} onCancel={() => setOpen(false)} okText="保存" cancelText="取消">
        <div className={styles.formGrid}>
          <label><span>标题</span><input className="input-quiet" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
          <label><span>说明与验收标准</span><textarea className="input-quiet" rows={4} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label><span>交付物</span><input className="input-quiet" value={draft.deliverable || ''} onChange={(e) => setDraft({ ...draft, deliverable: e.target.value })} /></label>
          <label><span>验收标准（每行一条）</span><textarea className="input-quiet" rows={3} value={(draft.acceptance_criteria || []).join('\n')} onChange={(e) => setDraft({ ...draft, acceptance_criteria: e.target.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) })} /></label>
          <label><span>优先级</span><Select value={draft.priority} onChange={(value: PlanPriority) => setDraft({ ...draft, priority: value })} options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} /></label>
          <label><span>开始时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.start_at)} onChange={(e) => setDraft({ ...draft, start_at: e.target.value || null })} /></label>
          <label><span>截止时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.due_at)} onChange={(e) => setDraft({ ...draft, due_at: e.target.value || null })} /></label>
          <label><span>邮件提醒时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.reminder_at)} onChange={(e) => setDraft({ ...draft, reminder_at: e.target.value || null })} /></label>
          <label className={styles.switchLine}><span>发送邮箱提醒</span><Switch checked={Boolean(draft.email_reminder)} onChange={(value) => setDraft({ ...draft, email_reminder: value ? 1 : 0 })} /></label>
        </div>
      </Modal>

      <Modal title={completionPlan ? `完成反馈：${completionPlan.title}` : '完成反馈'} open={Boolean(completionPlan)} onOk={() => void submitCompletion()} onCancel={() => setCompletionPlan(null)} confirmLoading={completing} okText="保存并标记完成" cancelText="暂不提交">
        <div className={styles.formGrid}>
          <p className={styles.completionHint}>记录交付物、得到的结论或未完全解决的问题。此内容将作为报告和下一次 AI 计划的可核验输入。</p>
          <label><span>实际成果与反馈</span><textarea className="input-quiet" rows={6} placeholder="例如：完成两篇论文的对比表，记录了 3 个方法差异；第二篇的实验设置仍需补证。" value={completionNotes} onChange={(event) => setCompletionNotes(event.target.value)} /></label>
          <label><span>实际投入（分钟）</span><InputNumber min={1} max={10080} value={completionMinutes} onChange={(value) => setCompletionMinutes(Number(value || 0))} /></label>
        </div>
      </Modal>
    </div>
  );
}

export default PlansPage;

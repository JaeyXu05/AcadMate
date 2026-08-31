import { useCallback, useEffect, useState } from 'react';
import { Button, Empty, Modal, Popconfirm, Select, Spin, Switch, message } from 'antd';
import { Sparkles, Trash2, Pencil, Plus, CalendarClock } from 'lucide-react';
import * as plansApi from '../services/plans';
import type { PlanInput, PlanPriority, PlanStatus, PlanSuggestion, ResearchPlan } from '../services/plans';
import { apiErrorMessage } from '../services/axios';
import styles from './ProductivityPage.module.css';

const emptyPlan: PlanInput = {
  title: '', description: '', status: 'todo', priority: 'medium', start_at: null,
  due_at: null, estimated_minutes: 60, actual_minutes: 0, reminder_at: null, email_reminder: 0,
};

function toLocalInput(value?: string | null): string {
  return value ? value.replace(' ', 'T').slice(0, 16) : '';
}

function PlansPage() {
  const [items, setItems] = useState<ResearchPlan[]>([]);
  const [suggestions, setSuggestions] = useState<PlanSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [coaching, setCoaching] = useState(false);
  const [editing, setEditing] = useState<ResearchPlan | null>(null);
  const [draft, setDraft] = useState<PlanInput>(emptyPlan);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await plansApi.listPlans());
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
        const rows = await plansApi.listPlans();
        if (!cancelled) {
          setItems(rows);
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
      start_at: item.start_at, due_at: item.due_at, estimated_minutes: item.estimated_minutes,
      actual_minutes: item.actual_minutes, reminder_at: item.reminder_at, email_reminder: item.email_reminder,
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
    await plansApi.updatePlan(item.id, { ...item, status });
    await load();
  };

  const coach = async () => {
    setCoaching(true);
    try { setSuggestions((await plansApi.getPlanSuggestions()).suggestions || []); }
    catch (error: any) { message.error(error?.response?.data?.message || 'AI 建议生成失败'); }
    finally { setCoaching(false); }
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <h2 className={styles.title}><CalendarClock size={16} strokeWidth={1.5} className="text-slate-600" /> 科研计划</h2>
      <p className={styles.subtitle}>用可验收的交付物规划研究工作；AI 仅基于已记录历史提出建议，不虚构进展。</p>
      <div className={styles.toolbar}>
        <Button icon={<Sparkles size={14} strokeWidth={1.5} className="text-slate-600" />} loading={coaching} onClick={coach}>AI 个性化建议</Button>
        <Button type="primary" icon={<Plus size={14} strokeWidth={1.5} />} onClick={() => showEditor()}>新增计划</Button>
      </div>
      {suggestions.length > 0 && <section className={styles.suggestionCard}><h3>HARNESS 计划建议</h3>{suggestions.map((item, index) => <p key={`${item.kind}-${index}`}><b>{item.kind}</b> · {item.text}</p>)}</section>}
      {loading ? <div className={styles.loading}><Spin /></div> : loadError ? <Empty description={loadError} /> : items.length === 0 ? <Empty description="暂无计划" /> : (
        <div className={styles.planGrid}>
          {items.map((item) => <article className={styles.planCard} key={item.id}>
            <div className={styles.planHeader}><h3>{item.title}</h3><span className={`${styles.priority} ${styles[item.priority]}`}>{item.priority}</span></div>
            <p>{item.description || '未填写说明'}</p>
            <div className={styles.planMeta}>截止：{item.due_at || '未设置'} · 预计 {item.estimated_minutes} 分钟</div>
            <div className={styles.planActions}>
              <Select value={item.status} size="small" onChange={(value) => void updateStatus(item, value)} options={[{ value: 'todo', label: '待办' }, { value: 'doing', label: '进行中' }, { value: 'done', label: '已完成' }, { value: 'cancelled', label: '已取消' }]} />
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
          <label><span>优先级</span><Select value={draft.priority} onChange={(value: PlanPriority) => setDraft({ ...draft, priority: value })} options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} /></label>
          <label><span>开始时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.start_at)} onChange={(e) => setDraft({ ...draft, start_at: e.target.value || null })} /></label>
          <label><span>截止时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.due_at)} onChange={(e) => setDraft({ ...draft, due_at: e.target.value || null })} /></label>
          <label><span>邮件提醒时间</span><input className="input-quiet" type="datetime-local" value={toLocalInput(draft.reminder_at)} onChange={(e) => setDraft({ ...draft, reminder_at: e.target.value || null })} /></label>
          <label className={styles.switchLine}><span>发送邮箱提醒</span><Switch checked={Boolean(draft.email_reminder)} onChange={(value) => setDraft({ ...draft, email_reminder: value ? 1 : 0 })} /></label>
        </div>
      </Modal>
    </div>
  );
}

export default PlansPage;

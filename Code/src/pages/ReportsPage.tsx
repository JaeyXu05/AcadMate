import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Button, Checkbox, Empty, InputNumber, Segmented, Spin, Switch, Tabs, message } from 'antd';
import { FileText, Mail, Presentation, RotateCw } from 'lucide-react';
import * as reportsApi from '../services/reports';
import type { PresentationJob, ProgressReport, ReportPeriod, ReportPreferences } from '../services/reports';
import { apiErrorMessage } from '../services/axios';
import styles from './ProductivityPage.module.css';

const defaults: ReportPreferences = {
  daily_enabled: false,
  weekly_enabled: false,
  monthly_enabled: false,
  email_enabled: false,
  daily_time: '20:00',
  weekly_day: 5,
  monthly_day: 1,
  timezone: 'Asia/Shanghai',
  smtp_configured: false,
};

const periodLabels: Record<ReportPeriod, string> = { daily: '日报', weekly: '周报', monthly: '月报' };

function reviewStatusLabel(status: string): string {
  if (status === 'LOCAL' || status === 'DEGRADED') return '本地摘要';
  return status;
}

function generationLabel(report: ProgressReport): string {
  const status = report.generation?.status;
  if (status === 'local' || report.review_status === 'LOCAL') return '本地记录摘要';
  if (status === 'fallback' || report.review_status === 'DEGRADED') {
    return report.generation?.reason
      ? `本地记录摘要（${report.generation.reason}）`
      : '本地记录摘要（智能体未完成）';
  }
  if (report.generation?.agent === 'progress_report_agent') {
    const bits = ['科研进展报告 Agent'];
    if (report.generation.model) bits.push(report.generation.model);
    if (status) bits.push(status);
    return bits.join(' · ');
  }
  return report.generation?.agent || '未知';
}

function inlineMarkdown(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => (
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : <span key={index}>{part}</span>
  ));
}

function ReportMarkdown({ content }: { content: string }) {
  return (
    <div className={styles.markdown}>
      {content.split(/\r?\n/).map((line, index) => {
        const text = line.trim();
        if (!text) return <div className={styles.markdownGap} key={index} />;
        if (text.startsWith('### ')) return <h4 key={index}>{inlineMarkdown(text.slice(4))}</h4>;
        if (text.startsWith('## ')) return <h3 key={index}>{inlineMarkdown(text.slice(3))}</h3>;
        if (text.startsWith('# ')) return <h2 key={index}>{inlineMarkdown(text.slice(2))}</h2>;
        if (/^\d+\.\s/.test(text)) return <div className={styles.numberedLine} key={index}>{inlineMarkdown(text)}</div>;
        if (text.startsWith('- ')) return <div className={styles.bulletLine} key={index}>{inlineMarkdown(text.slice(2))}</div>;
        return <p key={index}>{inlineMarkdown(text)}</p>;
      })}
    </div>
  );
}

function ReportsPage() {
  const params = new URLSearchParams(window.location.search);
  const initial = (params.get('period') as ReportPeriod) || 'daily';
  const [period, setPeriod] = useState<ReportPeriod>(['daily', 'weekly', 'monthly'].includes(initial) ? initial : 'daily');
  const [reports, setReports] = useState<ProgressReport[]>([]);
  const [prefs, setPrefs] = useState<ReportPreferences>(defaults);
  const [loading, setLoading] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [sendEmail, setSendEmail] = useState(false);
  const [pptJobs, setPptJobs] = useState<Record<number, PresentationJob>>({});
  const [pptGeneratingId, setPptGeneratingId] = useState<number | null>(null);
  const [pptDownloadingId, setPptDownloadingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReports(await reportsApi.listReports());
      setReportsError(null);
    } catch (error: unknown) {
      const text = apiErrorMessage(error, '报告列表加载失败');
      setReportsError(text);
      message.error(text);
    }
    try {
      setPrefs(await reportsApi.getPreferences());
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, '自动化设置加载失败'));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const items = await reportsApi.listReports();
        if (!cancelled) {
          setReports(items);
          setReportsError(null);
        }
      } catch (error: unknown) {
        if (!cancelled) {
          const text = apiErrorMessage(error, '报告列表加载失败');
          setReportsError(text);
          message.error(text);
        }
      }
      try {
        const preferences = await reportsApi.getPreferences();
        if (!cancelled) setPrefs(preferences);
      } catch (error: unknown) {
        if (!cancelled) message.error(apiErrorMessage(error, '自动化设置加载失败'));
      }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, []);

  const visible = useMemo(() => reports.filter((item) => item.period_type === period), [reports, period]);

  const generate = async () => {
    setGenerating(true);
    try {
      const report = await reportsApi.generateReport(period, sendEmail);
      const saved = { ...report, period_type: report.period_type || period };
      setReports((current) => [saved, ...current.filter((item) => item.id !== saved.id)]);
      const status = saved.generation?.status || saved.review_status;
      const reason = saved.generation?.reason;
      if (status === 'fallback' || saved.review_status === 'DEGRADED') {
        message.warning(
          `${periodLabels[period]}已用本地摘要生成${reason ? `（${reason}）` : '（报告智能体未完成）'}`,
        );
      } else {
        message.success(
          `${periodLabels[period]}已根据本地记录生成${sendEmail ? '并加入邮件发送队列' : ''}`,
        );
      }
    } catch (error: any) {
      message.error(apiErrorMessage(error, '报告生成失败'));
    } finally {
      setGenerating(false);
    }
  };

  const savePreferences = async () => {
    try {
      const { smtp_configured: _smtp, ...input } = prefs;
      await reportsApi.savePreferences(input);
      message.success('自动报告设置已保存');
      await load();
    } catch (error: any) {
      message.error(error?.response?.data?.message || '设置保存失败');
    }
  };

  const generatePpt = async (report: ProgressReport) => {
    setPptGeneratingId(report.id);
    try {
      let job = await reportsApi.createPresentation(report.id, { template: period === 'daily' ? 'group_meeting' : period, slide_count: period === 'daily' ? 5 : period === 'weekly' ? 8 : 12 });
      setPptJobs((current) => ({ ...current, [report.id]: job }));
      for (let attempt = 0; attempt < 45 && !['succeeded', 'failed'].includes(job.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        job = await reportsApi.getPresentation(job.id);
        setPptJobs((current) => ({ ...current, [report.id]: job }));
      }
      if (job.status === 'succeeded') message.success('PPT 已生成，可以下载');
      else if (job.status === 'failed') message.error(job.error || 'PPT 生成失败');
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, 'PPT 生成失败'));
    } finally {
      setPptGeneratingId(null);
    }
  };

  const downloadPpt = async (job: PresentationJob) => {
    setPptDownloadingId(job.id);
    try {
      const blob = await reportsApi.downloadPresentation(job.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${job.title || '科研报告'}.pptx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error: unknown) {
      message.error(apiErrorMessage(error, 'PPT 下载失败'));
    } finally {
      setPptDownloadingId(null);
    }
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <h2 className={styles.title}><FileText size={16} strokeWidth={1.5} className="text-slate-600" /> 科研进展报告</h2>
      <p className={styles.subtitle}>依据平台内可验证的计划、对话与成长记录生成；未记录的进展保持 unknown。</p>
      <Tabs
        activeKey={period}
        onChange={(key) => setPeriod(key as ReportPeriod)}
        items={(['daily', 'weekly', 'monthly'] as ReportPeriod[]).map((key) => ({ key, label: periodLabels[key] }))}
      />
      <div className={styles.toolbar}>
        <div className={styles.inlineControls}>
          <Checkbox checked={sendEmail} onChange={(event) => setSendEmail(event.target.checked)}>
            同时发送到注册邮箱
          </Checkbox>
          {!prefs.smtp_configured && sendEmail && <span className={styles.warning}>SMTP 尚未配置，邮件会进入待发送队列。</span>}
        </div>
        <Button type="primary" icon={<RotateCw size={14} strokeWidth={1.5} />} loading={generating} onClick={generate}>立即生成{periodLabels[period]}</Button>
      </div>

      <section className={styles.settingsCard}>
        <h3 className="inline-flex items-center gap-2"><Mail size={14} strokeWidth={1.5} className="text-slate-600" /> 自动报告与邮箱投递</h3>
        <div className={styles.settingsGrid}>
          <label><span>启用日报</span><Switch checked={prefs.daily_enabled} onChange={(value) => setPrefs({ ...prefs, daily_enabled: value })} /></label>
          <label><span>启用周报</span><Switch checked={prefs.weekly_enabled} onChange={(value) => setPrefs({ ...prefs, weekly_enabled: value })} /></label>
          <label><span>启用月报</span><Switch checked={prefs.monthly_enabled} onChange={(value) => setPrefs({ ...prefs, monthly_enabled: value })} /></label>
          <label><span>允许邮件发送</span><Switch checked={prefs.email_enabled} onChange={(value) => setPrefs({ ...prefs, email_enabled: value })} /></label>
          <label><span>发送时间</span><input className={`${styles.nativeInput} input-quiet`} type="time" value={prefs.daily_time} onChange={(e) => setPrefs({ ...prefs, daily_time: e.target.value })} /></label>
          <label><span>周报星期</span><Segmented size="small" value={prefs.weekly_day} options={[{ label: '一', value: 1 }, { label: '三', value: 3 }, { label: '五', value: 5 }, { label: '日', value: 0 }]} onChange={(value) => setPrefs({ ...prefs, weekly_day: Number(value) })} /></label>
          <label><span>月报日期</span><InputNumber min={1} max={28} value={prefs.monthly_day} onChange={(value) => setPrefs({ ...prefs, monthly_day: value || 1 })} /></label>
        </div>
        <Button onClick={savePreferences}>保存自动化设置</Button>
      </section>

      {loading ? <div className={styles.loading}><Spin /></div> : reportsError ? <Empty description={reportsError} /> : visible.length === 0 ? <Empty description={`尚无${periodLabels[period]}`} /> : (
        <div className={styles.reportList}>
          {visible.map((report) => (
            <article className={styles.reportCard} key={report.id}>
              <div className={styles.reportHeader}>
                <div><h3>{report.title}</h3><span>{report.period_start} 至 {report.period_end}</span></div>
                <span className={styles.passTag}>{reviewStatusLabel(report.review_status)}</span>
              </div>
              <div className={styles.evidenceLine}>生成：{generationLabel(report)}</div>
              <ReportMarkdown content={report.content_markdown} />
              <div className={styles.evidenceLine}>证据引用：{report.evidence_refs.length ? report.evidence_refs.join('、') : '本周期无外部证据引用'}</div>
              <div className={styles.reportActions}>
                <Button size="small" icon={<Presentation size={14} />} loading={pptGeneratingId === report.id} onClick={() => void generatePpt(report)}>
                  生成汇报 PPT
                </Button>
                {pptJobs[report.id]?.status === 'succeeded' && (
                  <Button type="link" size="small" loading={pptDownloadingId === pptJobs[report.id].id} onClick={() => void downloadPpt(pptJobs[report.id])}>下载 PPT</Button>
                )}
                {pptJobs[report.id] && pptJobs[report.id].status !== 'succeeded' && pptJobs[report.id].status !== 'failed' && <span className={styles.evidenceLine}>PPT 正在生成…</span>}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export default ReportsPage;

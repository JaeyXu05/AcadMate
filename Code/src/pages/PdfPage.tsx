import { useEffect, useState } from 'react';
import { Spin, Empty, Checkbox, App } from 'antd';
import { File, Zap, RotateCw, Lightbulb, BookOpen, Users, History, CheckCircle2, CircleAlert } from 'lucide-react';
import PdfUploader from '../components/PdfUploader';
import AdvisorCard from '../components/AdvisorCard';
import { analyzePdf, analyzePdfBatch, getPdfAnalysisJob, listPdfAnalysisJobs, listPdfDocuments, ANALYZE_TIMEOUT_MS, type PdfAnalysisJob, type PdfDocument } from '../services/pdf';
import type { PdfAnalysisResult } from '../types/pdf';
import PageCloseButton from '../components/PageCloseButton';
import styles from './PdfPage.module.css';

type Stage = 'upload' | 'ready' | 'analyzing' | 'done';

const ANALYZE_TIMEOUT_MIN = Math.round(ANALYZE_TIMEOUT_MS / 60000);

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

function analyzingPhase(sec: number): string {
  if (sec < 20) return '正在提取 PDF 文本…';
  if (sec < 90) return '正在语义检索匹配导师…';
  return '正在模型重排，请继续等待…';
}

function analysisJobStatusLabel(status: PdfAnalysisJob['status']): string {
  if (status === 'queued') return '排队中';
  if (status === 'running') return '分析中';
  if (status === 'succeeded') return '已完成';
  return '失败';
}

function analysisJobTime(job: PdfAnalysisJob): string {
  const value = job.completedAt || job.updatedAt || job.createdAt;
  if (!value) return '';
  const time = new Date(value.replace(' ', 'T'));
  return Number.isNaN(time.getTime()) ? value : time.toLocaleString();
}

function PdfPage() {
  const { message } = App.useApp();
  const [stage, setStage] = useState<Stage>('upload');
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>('');
  const [result, setResult] = useState<PdfAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [activeJobIds, setActiveJobIds] = useState<string[]>([]);
  const [documents, setDocuments] = useState<PdfDocument[]>([]);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [analysisJobs, setAnalysisJobs] = useState<PdfAnalysisJob[]>([]);
  const [analysisStartedAt, setAnalysisStartedAt] = useState<number | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    if (stage !== 'analyzing') {
      setElapsedSec(0);
      return;
    }
    const started = analysisStartedAt || Date.now();
    const id = window.setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [stage, analysisStartedAt]);

  const applyAnalysisJob = (job: PdfAnalysisJob) => {
    setJobId(job.jobId);
    setUploadId(job.documentId);
    setFilename(typeof job.result?.batchLabel === 'string' && job.result.batchLabel ? job.result.batchLabel : job.filename);
    setSelectedDocumentIds([job.documentId]);
    if (job.status === 'succeeded' && job.result) {
      setResult(job.result);
      setError(null);
      setStage('done');
      return;
    }
    if (job.status === 'queued' || job.status === 'running') {
      setActiveJobIds((current) => current.includes(job.jobId) ? current : [...current, job.jobId]);
      setResult(null);
      setError(null);
      setAnalysisStartedAt(job.startedAt ? Date.parse(job.startedAt) : Date.now());
      setStage('analyzing');
      return;
    }
    setResult(null);
    setError(job.error || 'PDF 分析失败，请重新开始分析');
    setStage('ready');
  };

  const refreshAnalysisJobs = async () => {
    const jobs = await listPdfAnalysisJobs();
    setAnalysisJobs(jobs);
    return jobs;
  };

  const refreshDocuments = async () => {
    const items = await listPdfDocuments();
    setDocuments(items);
    return items;
  };

  // 返回 PDF 页面时，从后端恢复最近一次任务，而不是依赖页面离开前的内存状态。
  useEffect(() => {
    let cancelled = false;
    void Promise.all([refreshDocuments(), refreshAnalysisJobs()])
      .then(([, jobs]) => {
        if (!cancelled && jobs[0]) applyAnalysisJob(jobs[0]);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  // 页面只轮询轻量任务状态；真正的 PDF 分析在后端独立运行。
  useEffect(() => {
    if (!activeJobIds.length) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const jobs = await Promise.all(activeJobIds.map((id) => getPdfAnalysisJob(id)));
        if (!cancelled) {
          setAnalysisJobs((current) => [
            ...jobs,
            ...current.filter((item) => !jobs.some((job) => job.jobId === item.jobId)),
          ]);
          const allFinished = jobs.every((job) => job.status === 'succeeded' || job.status === 'failed');
          if (allFinished) {
            setActiveJobIds([]);
            const selectedJob = jobs.find((job) => job.jobId === jobId) || jobs[0];
            if (selectedJob && stage === 'analyzing') applyAnalysisJob(selectedJob);
            void refreshDocuments();
          }
        }
      } catch {
        // 暂时的网络波动不改变任务状态，下一轮继续读取。
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeJobIds, jobId, stage]);

  const handleUploaded = (id: string, name: string) => {
    setUploadId(id);
    setFilename(name);
    setResult(null);
    setError(null);
    setJobId(null);
    setActiveJobIds([]);
    setDocuments((current) => current.some((item) => item.documentId === id)
      ? current
      : [{ documentId: id, userId: 0, originalName: name, pageCount: null, parseStatus: 'uploaded', createdAt: null, updatedAt: null }, ...current]);
    setSelectedDocumentIds((current) => current.includes(id) ? current : [...current, id]);
    void refreshDocuments();
    setAnalysisStartedAt(null);
    setStage('ready');
  };

  const handleAnalyze = async () => {
    if (!selectedDocumentIds.length) {
      message.error('请先在下方历史列表中选择至少一个 PDF');
      return;
    }
    setError(null);
    try {
      let jobIds: string[] = [];
      if (selectedDocumentIds.length === 1) {
        const single = await analyzePdf(selectedDocumentIds[0]);
        jobIds = [single.job_id];
      } else {
        const batch = await analyzePdfBatch(selectedDocumentIds);
        jobIds = batch.jobs.map((job) => job.jobId);
      }
      if (!jobIds.length) throw new Error('没有成功创建分析任务');
      setJobId(jobIds[0] || null);
      setActiveJobIds(jobIds);
      void refreshAnalysisJobs();
      setAnalysisStartedAt(Date.now());
      setStage('analyzing');
    } catch (err) {
      setError(analyzeErrorMessage(err));
      setStage('ready');
    }
  };

  const handleReset = () => {
    setStage('upload');
    setUploadId(null);
    setFilename('');
    setResult(null);
    setError(null);
    setJobId(null);
    setActiveJobIds([]);
    setSelectedDocumentIds([]);
    setAnalysisStartedAt(null);
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <File size={16} strokeWidth={1.5} className="text-slate-600" />
        PDF 分析
      </h2>
      <p className={styles.subtitle}>上传论文 PDF，自动总结全文要点并推荐研究方向匹配的导师</p>

      {documents.length > 0 && (
        <section className={styles.history}>
          <div className={styles.historyHeader}>
            <h3 className={styles.historyTitle}><History size={15} strokeWidth={1.5} /> PDF 历史记录</h3>
            <span>单选分析单篇；多选会把所选文献合并成一次联合分析</span>
          </div>
          <div className={styles.historyList}>
            {documents.map((document) => {
              const latestJob = analysisJobs.find((job) => job.documentId === document.documentId);
              const selected = selectedDocumentIds.includes(document.documentId);
              return (
                <div key={document.documentId} className={`${styles.historyItem} ${selected ? styles.historyItemActive : ''}`}>
                  <Checkbox
                    checked={selected}
                    onChange={(event) => {
                      setSelectedDocumentIds((current) => event.target.checked
                        ? [...current, document.documentId]
                        : current.filter((id) => id !== document.documentId));
                    }}
                  />
                  <File size={15} strokeWidth={1.5} className={styles.historyFileIcon} />
                  <span className={styles.historyMain}>
                    <span className={styles.historyFilename}>{document.originalName || document.documentId}</span>
                    <span className={styles.historyMeta}>
                      {document.pageCount ? `${document.pageCount} 页 · ` : ''}
                      {latestJob ? `${analysisJobTime(latestJob)} · ${analysisJobStatusLabel(latestJob.status)}` : '尚未分析'}
                    </span>
                  </span>
                  {latestJob && latestJob.status !== 'failed' && (
                    <button type="button" className={styles.historyViewBtn} onClick={() => applyAnalysisJob(latestJob)}>
                      {latestJob.result ? '查看' : '进度'}
                    </button>
                  )}
                  {latestJob?.status === 'succeeded' ? (
                    <CheckCircle2 size={16} className={styles.historyDone} />
                  ) : latestJob?.status === 'failed' ? (
                    <CircleAlert size={16} className={styles.historyFailed} />
                  ) : latestJob ? (
                    <Spin size="small" />
                  ) : null}
                </div>
              );
            })}
          </div>
          <div className={styles.historyActions}>
            <button className={styles.analyzeBtn} onClick={() => void handleAnalyze()} disabled={!selectedDocumentIds.length || stage === 'analyzing'}>
              <Zap size={14} strokeWidth={1.5} className="text-slate-600" />
              {stage === 'analyzing'
                ? '分析中…'
                : selectedDocumentIds.length > 1
                  ? `合并分析（${selectedDocumentIds.length} 篇）`
                  : '开始分析'}
            </button>
          </div>
        </section>
      )}

      {/* 上传区 */}
      {stage !== 'analyzing' && (
        <>
          <PdfUploader onUploaded={handleUploaded} />
          {error && <div className={styles.error}>{error}</div>}
        </>
      )}

      {/* 分析中 */}
      {stage === 'analyzing' && (
        <div className={styles.analyzingWrap}>
          <Spin size="large" />
          <span>{analyzingPhase(elapsedSec)}</span>
          <span className={styles.analyzingHint}>
            已等待 {formatElapsed(elapsedSec)}。任务已转入后台，离开本页面不会中断；回来后会自动恢复进度和结果。语义检索与模型重排通常需要数分钟，最长约 {ANALYZE_TIMEOUT_MIN} 分钟。
          </span>
        </div>
      )}

      {/* 分析结果 */}
      {stage === 'done' && result && (
        <>
          <div className={styles.toolbar}>
            <span className={styles.fileTag}>
              <File size={14} strokeWidth={1.5} className="text-slate-600" />
              {filename}
            </span>
            <button className={styles.resetBtn} onClick={handleReset}>
              <RotateCw size={14} strokeWidth={1.5} className="text-slate-600" />
              分析另一篇
            </button>
          </div>

          {/* 总结 */}
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <BookOpen size={14} strokeWidth={1.5} className="text-slate-600" />
              全文总结
            </h3>
            <div className={styles.summaryCard}>
              <p className={styles.summaryText}>{result.summary}</p>
            </div>
          </div>

          {/* 关键要点 */}
          {result.keyPoints.length > 0 && (
            <div className={styles.section}>
              <h3 className={styles.sectionTitle}>
              <Lightbulb size={14} strokeWidth={1.5} className="text-slate-600" />
              关键要点
              </h3>
              <ul className={styles.keyPoints}>
                {result.keyPoints.map((kp, i) => (
                  <li key={i} className={styles.keyPoint}>
                    <span className={styles.keyPointDot} />
                    <span>{kp}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 推荐导师 */}
          <div className={styles.divider} />
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <Users size={14} strokeWidth={1.5} className="text-slate-600" />
              推荐导师
            </h3>
            {result.suggestedAdvisors.length === 0 ? (
              <Empty
                description={<span className="text-stone-400">暂无匹配导师</span>}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ) : (
              <div className={styles.advisorList}>
                {result.suggestedAdvisors.map((a) => (
                  <AdvisorCard key={a.id} advisor={a} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const ANALYZE_TIMEOUT_HINT =
  `等待超过 ${ANALYZE_TIMEOUT_MIN} 分钟仍未返回。长 PDF 的语义检索和模型重排可能更久；请确认 A 端（8000）在跑后再试。立刻失败会显示具体原因，而不是这条提示。`;

function analyzeErrorMessage(err: unknown): string {
  if (!err || typeof err !== 'object') return '分析失败，请重试';
  const axiosLike = err as {
    code?: string;
    message?: string;
    response?: { data?: { message?: string } };
  };
  if (axiosLike.response?.data?.message) return axiosLike.response.data.message;
  if (
    axiosLike.code === 'ECONNABORTED' ||
    (typeof axiosLike.message === 'string' && axiosLike.message.toLowerCase().includes('timeout'))
  ) {
    return ANALYZE_TIMEOUT_HINT;
  }
  if (!axiosLike.response) {
    return '分析请求未得到后端响应（连接中断）。若已等待数分钟，请稍后重试；若几乎立刻失败，请确认 D 端（3001）在跑。';
  }
  return '分析失败，请重试';
}

export default PdfPage;

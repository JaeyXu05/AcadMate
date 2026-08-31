import { useEffect, useState } from 'react';
import { Spin, Empty } from 'antd';
import { File, Zap, RotateCw, Lightbulb, BookOpen, Users } from 'lucide-react';
import PdfUploader from '../components/PdfUploader';
import AdvisorCard from '../components/AdvisorCard';
import { analyzePdf, ANALYZE_TIMEOUT_MS } from '../services/pdf';
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

function PdfPage() {
  const [stage, setStage] = useState<Stage>('upload');
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>('');
  const [result, setResult] = useState<PdfAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  useEffect(() => {
    if (stage !== 'analyzing') {
      setElapsedSec(0);
      return;
    }
    const started = Date.now();
    const id = window.setInterval(() => {
      setElapsedSec(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [stage]);

  const handleUploaded = (id: string, name: string) => {
    setUploadId(id);
    setFilename(name);
    setResult(null);
    setError(null);
    setStage('ready');
  };

  const handleAnalyze = async () => {
    if (!uploadId) return;
    setStage('analyzing');
    setError(null);
    try {
      const res = await analyzePdf(uploadId);
      setResult(res);
      // 分析后文档会作为可复用资产保留，允许对同一 document_id 再次分析
      setStage('done');
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
  };

  return (
    <div className={`${styles.container} pt-12`}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <File size={16} strokeWidth={1.5} className="text-slate-600" />
        PDF 分析
      </h2>
      <p className={styles.subtitle}>上传论文 PDF，自动总结全文要点并推荐研究方向匹配的导师</p>

      {/* 上传区 */}
      {(stage === 'upload' || stage === 'ready') && (
        <>
          <PdfUploader onUploaded={handleUploaded} />
          {error && <div className={styles.error}>{error}</div>}
          {stage === 'ready' && (
            <>
              <div className={styles.toolbar} style={{ marginTop: 20 }}>
                <span className={styles.fileTag}>
                  <File size={14} strokeWidth={1.5} className="text-slate-600" />
                  {filename}
                </span>
                <button className={styles.analyzeBtn} onClick={handleAnalyze}>
                  <Zap size={14} strokeWidth={1.5} className="text-slate-600" />
                  开始分析
                </button>
              </div>
            </>
          )}
        </>
      )}

      {/* 分析中 */}
      {stage === 'analyzing' && (
        <div className={styles.analyzingWrap}>
          <Spin size="large" />
          <span>{analyzingPhase(elapsedSec)}</span>
          <span className={styles.analyzingHint}>
            已等待 {formatElapsed(elapsedSec)}。语义检索与模型重排通常需要数分钟，最长约 {ANALYZE_TIMEOUT_MIN} 分钟；A 端未启动会在几秒内报错，不会一直转圈。
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

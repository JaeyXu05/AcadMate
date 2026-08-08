import { useState } from 'react';
import { Spin, Empty } from 'antd';
import { FilePdfOutlined, ThunderboltOutlined, ReloadOutlined, BulbOutlined, ReadOutlined, TeamOutlined } from '@ant-design/icons';
import PdfUploader from '../components/PdfUploader';
import AdvisorCard from '../components/AdvisorCard';
import { analyzePdf } from '../services/pdf';
import type { PdfAnalysisResult } from '../types/pdf';
import PageCloseButton from '../components/PageCloseButton';
import styles from './PdfPage.module.css';

type Stage = 'upload' | 'ready' | 'analyzing' | 'done';

function PdfPage() {
  const [stage, setStage] = useState<Stage>('upload');
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [filename, setFilename] = useState<string>('');
  const [result, setResult] = useState<PdfAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      setStage('done');
      // 分析后 upload_id 在后端已被消费，重置以便"再分析"需重新上传
      setUploadId(null);
    } catch (err) {
      const msg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { message?: string } } }).response?.data?.message
          : undefined;
      setError(msg ?? '分析失败，请重试');
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
    <div className={styles.container}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <FilePdfOutlined style={{ color: '#667eea' }} />
        PDF 分析
      </h2>
      <p className={styles.subtitle}>上传论文 PDF，自动总结全文要点并推荐研究方向匹配的导师</p>

      {/* 上传区 */}
      {(stage === 'upload' || stage === 'ready') && (
        <>
          <PdfUploader onUploaded={handleUploaded} />
          {error && (
            <div style={{ color: '#ff7875', fontSize: 13, marginTop: 12 }}>{error}</div>
          )}
          {stage === 'ready' && (
            <>
              <div className={styles.toolbar} style={{ marginTop: 20 }}>
                <span className={styles.fileTag}>
                  <FilePdfOutlined />
                  {filename}
                </span>
                <button className={styles.analyzeBtn} onClick={handleAnalyze}>
                  <ThunderboltOutlined />
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
          <span>正在分析论文内容，请稍候…</span>
          <span className={styles.analyzingHint}>这一步可能需要几秒</span>
        </div>
      )}

      {/* 分析结果 */}
      {stage === 'done' && result && (
        <>
          <div className={styles.toolbar}>
            <span className={styles.fileTag}>
              <FilePdfOutlined />
              {filename}
            </span>
            <button className={styles.resetBtn} onClick={handleReset}>
              <ReloadOutlined />
              分析另一篇
            </button>
          </div>

          {/* 总结 */}
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <ReadOutlined style={{ color: '#667eea' }} />
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
                <BulbOutlined style={{ color: '#667eea' }} />
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
              <TeamOutlined style={{ color: '#667eea' }} />
              推荐导师
            </h3>
            {result.suggestedAdvisors.length === 0 ? (
              <Empty
                description={<span style={{ color: 'rgba(255,255,255,0.45)' }}>暂无匹配导师</span>}
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

export default PdfPage;

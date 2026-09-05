import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Spin, Empty, App } from 'antd';
import { Mail, BookOpen } from 'lucide-react';
import { getAdvisorDetail } from '../services/advisor';
import { listAgentArtifacts, readMentorPapers, uploadPaperForRetry } from '../services/agent';
import type { AdvisorDetail } from '../types/advisor';
import type { PaperReadResult } from '../services/agent';
import PageCloseButton from '../components/PageCloseButton';
import StarButton from '../components/StarButton';
import ReasoningChain from '../components/ReasoningChain';
import PdfUploader from '../components/PdfUploader';
import styles from './AdvisorDetailPage.module.css';

function AdvisorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const [advisor, setAdvisor] = useState<AdvisorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [readResult, setReadResult] = useState<PaperReadResult | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [evidenceRecords, setEvidenceRecords] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAdvisorDetail(id)
      .then((d) => {
        if (!cancelled) setAdvisor(d);
      })
      .catch(() => {
        if (!cancelled) setError('加载导师详情失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    listAgentArtifacts({ advisorId: id })
      .then((rows) => {
        if (cancelled || !Array.isArray(rows)) return;
        const paper = rows.find((row: any) => row.skillId === 'paper_qa');
        if (paper?.payload) setReadResult(paper.payload as PaperReadResult);
        const mentor = rows.find((row: any) => row.skillId === 'mentor_match');
        const records = (mentor?.payload as { evidence_records?: unknown })?.evidence_records;
        if (Array.isArray(records)) setEvidenceRecords(records as Array<Record<string, unknown>>);
      })
      .catch(() => {
        /* 刷新后无产物时保持空 */
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const handleReadPapers = async (paperId?: number) => {
    if (!advisor || reading) return;
    setReading(true);
    setReadError(null);
    try {
      const result = await readMentorPapers(advisor.id, { paperId });
      setReadResult(result);
      if (result.review_status === 'PASS') {
        message.success('Paper Claw 阅读通过审核，已写入成长状态');
      } else if (result.review_status === 'NEED_MORE_INPUT' || result.review_status === 'RESEARCH_AGAIN') {
        message.warning(result.artifact?.error || '论文尚未解析入库，请在本页上传 PDF 后重试同一 paper_id');
      } else {
        message.warning(`论文证据未通过审核：${result.review_status || result.status || 'UNKNOWN'}`);
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : '阅读论文失败';
      setReadError(text);
      message.error(text);
    } finally {
      setReading(false);
    }
  };

  const publicationTitles = (readResult?.artifact?.publications ?? [])
    .map((item) => (typeof item === 'string' ? item : String((item as { title?: string })?.title ?? '')))
    .filter(Boolean);
  const retrievedChunks = readResult?.artifact?.retrieved_chunks ?? [];

  if (loading) {
    return (
      <div className={styles.container}>
        <PageCloseButton />
        <div className={styles.loadingWrap}>
          <Spin size="large" />
        </div>
      </div>
    );
  }

  if (error || !advisor) {
    return (
      <div className={styles.container}>
        <PageCloseButton />
        <div className={styles.errorWrap}>
          <Empty
            description={<span className="text-stone-400">{error ?? '未找到该导师'}</span>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      </div>
    );
  }

  const scorePercent = Math.round(advisor.matchScore * 10) / 10;

  return (
    <div className={styles.container}>
      <PageCloseButton />

      {/* 头部 */}
      <div className={styles.header}>
        <div className={styles.avatar}>{advisor.name.charAt(0)}</div>
        <div className={styles.headerInfo}>
          <div className={styles.nameRow}>
            <span className={styles.name}>{advisor.name}</span>
            <span className={styles.title}>{advisor.title}</span>
          </div>
          <div className={styles.department}>{advisor.department}</div>
          <div className={styles.headerActions}>
            <StarButton advisorId={advisor.id} variant="detail" />
            <button
              className={styles.emailBtn}
              onClick={() => navigate(`/email?advisor_id=${encodeURIComponent(advisor.id)}`)}
            >
              <Mail size={14} strokeWidth={1.5} className="text-slate-600" />
              给这位导师写邮件
            </button>
            <button
              className={styles.readBtn}
              onClick={() => { void handleReadPapers(); }}
              disabled={reading}
            >
              <BookOpen size={14} strokeWidth={1.5} className="text-slate-600" />
              {reading ? '阅读中…' : '阅读其论文'}
            </button>
          </div>
        </div>
      </div>

      {/* 标签 */}
      {advisor.tags.length > 0 && (
        <div className={styles.tagsRow}>
          {advisor.tags.slice(0, 8).map((tag) => (
            <span key={tag} className="border border-stone-200 px-2 py-0.5 text-[11px] text-stone-500">
              {tag}
            </span>
          ))}
        </div>
      )}

      {/* 指标 */}
      <div className={styles.section}>
        <div className={styles.metricGrid}>
          {typeof advisor.papers === 'number' && Number.isFinite(advisor.papers) && advisor.papers > 0 && (
            <div className={styles.metricCell}>
              <div className={styles.metricCellLabel}>论文数</div>
              <div className={styles.metricCellValue}>{advisor.papers}</div>
            </div>
          )}
          <div className={styles.metricCell}>
            <div className={styles.metricCellLabel}>MATCH SCORE</div>
            <div className={styles.metricCellValue}>
              {Number.isFinite(advisor.matchScore) && advisor.matchScore > 0 ? scorePercent : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 个人简介 */}
      {advisor.bio && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>个人简介</h3>
          <p className={styles.sectionText}>{advisor.bio}</p>
        </div>
      )}

      {/* 招生意向 */}
      {advisor.recruiting && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>招生意向</h3>
          <p className={styles.sectionText}>{advisor.recruiting}</p>
        </div>
      )}

      {/* 代表论文 */}
      {advisor.recentPapers && advisor.recentPapers.length > 0 && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>代表论文</h3>
          {advisor.recentPapers.map((p, i) => (
            <div key={i} className={styles.paperItem}>
              <span style={{ flex: 1 }}>{p.title}</span>
              {p.venue && <span className={styles.paperVenue}>{p.venue}</span>}
              {p.year && <span className={styles.paperYear}>{p.year}</span>}
            </div>
          ))}
        </div>
      )}

      {(readError || readResult || evidenceRecords.length > 0) && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>Paper Skill 阅读结果</h3>
          {readResult?.review_status && (
            <p className={styles.sectionText}>Review：{readResult.review_status}</p>
          )}
          {readError && <p className={styles.sectionText}>{readError}</p>}
          {readResult?.artifact?.note && (
            <p className={styles.sectionText}>{readResult.artifact.note}</p>
          )}
          {readResult?.artifact?.error && (
            <p className={styles.sectionText}>{readResult.artifact.error}</p>
          )}
          {(readResult?.review_status === 'NEED_MORE_INPUT' || readResult?.review_status === 'RESEARCH_AGAIN') && (
            <div style={{ marginTop: 12 }}>
              <p className={styles.sectionText}>在此上传 PDF，会写入同一 paper_id 并自动重试 paper_qa，无需新开一轮空转。</p>
              <PdfUploader
                uploadFn={async (file) => {
                  const uploaded = await uploadPaperForRetry({
                    file,
                    candidateId: advisor.id,
                    paperId: readResult?.artifact?.paper_id,
                    runId: readResult?.run_id,
                  });
                  await handleReadPapers(uploaded.paper_id || uploaded.retry?.paper_id);
                  return { upload_id: String(uploaded.paper_id), filename: file.name };
                }}
              />
            </div>
          )}
          {readResult?.artifact?.retry && readResult.review_status === 'REVISE' && (
            <p className={styles.sectionText}>
              Retry：答案需要引用并通过词重叠核验的 chunk，而不是重新创建无关运行。
            </p>
          )}
          {publicationTitles.map((title) => (
            <div key={title} className={styles.paperItem}>
              <span style={{ flex: 1 }}>{title}</span>
            </div>
          ))}
          {readResult?.artifact?.answer && (
            <p className={styles.sectionText}>{readResult.artifact.answer}</p>
          )}
          {readResult?.evidence_refs && readResult.evidence_refs.length > 0 && (
            <p className={styles.sectionText}>引用 Evidence：{readResult.evidence_refs.join('、')}</p>
          )}
          {retrievedChunks.filter((chunk) => chunk.cited !== false).map((chunk) => (
            <div key={chunk.evidence_id ?? chunk.chunk_id} className={styles.paperItem}>
              <span style={{ flex: 1 }}>
                [{chunk.evidence_id}] {chunk.content}
              </span>
            </div>
          ))}
          {evidenceRecords.map((record) => (
            <div key={String(record.evidence_id || '')} className={styles.paperItem}>
              <span style={{ flex: 1 }}>
                [{String(record.evidence_id || '')}] {String(record.title || record.extracted_fact || record.source_uri || '')}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 联系方式 */}
      {advisor.contact && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>联系方式</h3>
          <div className={styles.kvRow}>{advisor.contact}</div>
        </div>
      )}

      {/* 推理链 */}
      {advisor.explanation && (
        <div className={styles.section}>
          <h3 className={styles.sectionTitle}>推荐理由</h3>
          <ReasoningChain text={advisor.explanation} />
        </div>
      )}
    </div>
  );
}

export default AdvisorDetailPage;

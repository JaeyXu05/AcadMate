import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Tag, Spin, Empty } from 'antd';
import { MailOutlined } from '@ant-design/icons';
import { getAdvisorDetail } from '../services/advisor';
import type { AdvisorDetail } from '../types/advisor';
import PageCloseButton from '../components/PageCloseButton';
import StarButton from '../components/StarButton';
import ReasoningChain from '../components/ReasoningChain';
import styles from './AdvisorDetailPage.module.css';

const TAG_COLORS = ['#667eea', '#52c41a', '#fa8c16', '#eb2f96', '#13c2c2', '#f5222d'];

function AdvisorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [advisor, setAdvisor] = useState<AdvisorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    return () => {
      cancelled = true;
    };
  }, [id]);

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
            description={<span style={{ color: 'rgba(255,255,255,0.45)' }}>{error ?? '未找到该导师'}</span>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      </div>
    );
  }

  const scorePercent = Math.round(advisor.matchScore);
  const scoreColor = scorePercent >= 80 ? '#52c41a' : scorePercent >= 60 ? '#fa8c16' : '#f5222d';

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
              <MailOutlined />
              给这位导师写邮件
            </button>
          </div>
        </div>
      </div>

      {/* 标签 */}
      {advisor.tags.length > 0 && (
        <div className={styles.tagsRow}>
          {advisor.tags.map((tag, i) => (
            <Tag key={tag} color={TAG_COLORS[i % TAG_COLORS.length]}>
              {tag}
            </Tag>
          ))}
        </div>
      )}

      {/* 指标 */}
      <div className={styles.section}>
        <div className={styles.metricGrid}>
          <div className={styles.metricCell}>
            <div className={styles.metricCellLabel}>论文数</div>
            <div className={styles.metricCellValue}>{advisor.papers}</div>
          </div>
          <div className={styles.metricCell}>
            <div className={styles.metricCellLabel}>匹配度</div>
            <div className={styles.metricCellValue} style={{ color: scoreColor }}>
              {scorePercent}%
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

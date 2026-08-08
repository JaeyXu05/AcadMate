import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Tag } from 'antd';
import { DownOutlined, RightOutlined } from '@ant-design/icons';
import type { Advisor } from '../types/search';
import ReasoningChain from './ReasoningChain';
import StarButton from './StarButton';
import styles from './AdvisorCard.module.css';

interface AdvisorCardProps {
  advisor: Advisor;
  compact?: boolean;
}

// 标签配色方案（循环使用）
const TAG_COLORS = ['#667eea', '#52c41a', '#fa8c16', '#eb2f96', '#13c2c2', '#f5222d'];

function AdvisorCard({ advisor, compact = false }: AdvisorCardProps) {
  const navigate = useNavigate();
  const [reasoningOpen, setReasoningOpen] = useState(false);

  const handleOpenDetail = () => {
    navigate(`/advisor/${encodeURIComponent(advisor.id)}`);
  };

  const scorePercent = Math.round(advisor.matchScore);
  const scoreColor =
    scorePercent >= 80 ? '#52c41a' : scorePercent >= 60 ? '#fa8c16' : '#f5222d';

  return (
    <div
      className={`${styles.card} ${compact ? styles.cardCompact : ''}`}
      onClick={handleOpenDetail}
      style={{ cursor: 'pointer' }}
    >
      {/* 基本信息 */}
      <div className={styles.cardHeader}>
        <div className={styles.nameRow}>
          <span className={styles.name}>{advisor.name}</span>
          <span className={styles.title}>{advisor.title}</span>
          <span className={styles.department}>{advisor.department}</span>
        </div>
      </div>

      {/* 研究方向标签 */}
      <div className={styles.tagsRow}>
        {advisor.tags.map((tag, i) => (
          <Tag key={tag} color={TAG_COLORS[i % TAG_COLORS.length]}>
            {tag}
          </Tag>
        ))}
      </div>

      {/* 指标行 */}
      <div className={styles.metrics}>
        <span className={styles.metric}>
          <span className={styles.metricLabel}>论文</span>
          <span className={styles.metricValue}>{advisor.papers} 篇</span>
        </span>
        <span className={styles.metric}>
          <span className={styles.metricLabel}>匹配度</span>
          <span className={styles.metricValue} style={{ color: scoreColor }}>
            {scorePercent}%
          </span>
        </span>
      </div>

      {/* 匹配度进度条 */}
      <div className={styles.scoreBar}>
        <div
          className={styles.scoreFill}
          style={{
            width: `${scorePercent}%`,
            backgroundColor: scoreColor,
          }}
        />
      </div>

      {/* 推理链 */}
      {advisor.explanation && (
        <div className={styles.reasoningWrap}>
          <button
            className={styles.reasoningBtn}
            onClick={(e) => {
              e.stopPropagation();
              setReasoningOpen(!reasoningOpen);
            }}
          >
            {reasoningOpen ? <DownOutlined /> : <RightOutlined />}
            {reasoningOpen ? '收起推理链' : '展开推理链 🔍'}
          </button>
          {reasoningOpen && (
            <ReasoningChain text={advisor.explanation} />
          )}
        </div>
      )}

      {/* 操作按钮 */}
      <div className={styles.actions} onClick={(e) => e.stopPropagation()}>
        <StarButton advisorId={advisor.id} variant="card" />
        <button
          className={styles.actionBtn}
          onClick={handleOpenDetail}
        >
          查看详情
        </button>
      </div>
    </div>
  );
}

export default AdvisorCard;

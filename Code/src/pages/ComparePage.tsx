import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Spin, Empty } from 'antd';
import { getAdvisorDetail } from '../services/advisor';
import type { AdvisorDetail } from '../types/advisor';
import PageCloseButton from '../components/PageCloseButton';
import styles from './ComparePage.module.css';

interface CompareLocationState {
  advisor_ids?: string[];
}

/** 状态持久化键：刷新后不丢已选导师（sessionStorage，关标签页即清） */
const COMPARE_IDS_KEY = 'compare:advisor_ids';

function readPersistedIds(): string[] {
  try {
    const raw = sessionStorage.getItem(COMPARE_IDS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
    }
  } catch {
    /* 损坏不阻断 */
  }
  return [];
}

function ComparePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [advisors, setAdvisors] = useState<AdvisorDetail[]>([]);
  const [loading, setLoading] = useState(true);

  // 初始化：优先取跳转带来的 location.state；刷新后它没了，回退到 sessionStorage 持久化。
  const [ids] = useState<string[]>(() => {
    const fromState = (location.state as CompareLocationState | null)?.advisor_ids ?? [];
    return fromState.length > 0 ? fromState : readPersistedIds();
  });

  // 把本次对比的导师 id 存下来，供刷新恢复（latest 覆盖）。
  useEffect(() => {
    if (ids.length > 0) {
      try {
        sessionStorage.setItem(COMPARE_IDS_KEY, JSON.stringify(ids));
      } catch {
        /* 隐私模式可能抛错，忽略 */
      }
    }
  }, [ids]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const results = await Promise.all(
        ids.map((id) => getAdvisorDetail(id).catch(() => null)),
      );
      if (!cancelled) {
        setAdvisors(results.filter((d): d is AdvisorDetail => d !== null));
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [ids]);

  // 各指标最优值（用于高亮）
  const maxPapers = Math.max(...advisors.map((a) => a.papers), 0);
  const maxMatch = Math.max(...advisors.map((a) => a.matchScore), 0);

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

  if (advisors.length < 2) {
    return (
      <div className={styles.container}>
        <PageCloseButton />
        <div className={styles.errorWrap}>
          <Empty
            description={
              <span className="text-stone-400">
                需要至少 2 位导师才能对比，请返回收藏夹重新选择
              </span>
            }
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
          <button
            onClick={() => navigate('/favorites')}
            style={{
              marginTop: 16,
              padding: '8px 20px',
              border: '1px solid rgba(28,25,23,0.12)',
              background: '#fff',
              color: '#1c1917',
              cursor: 'pointer',
            }}
          >
            返回收藏夹
          </button>
        </div>
      </div>
    );
  }

  const rows: { label: string; render: (a: AdvisorDetail) => React.ReactNode; best?: (a: AdvisorDetail) => boolean }[] = [
    { label: '职称', render: (a) => a.title },
    { label: '院系', render: (a) => a.department },
    {
      label: '研究方向',
      render: (a) => (
        <div className={styles.cellTags}>
          {a.tags.map((t) => (
            <span key={t} className={styles.cellTag}>{t}</span>
          ))}
        </div>
      ),
    },
    { label: '论文数', render: (a) => a.papers, best: (a) => a.papers === maxPapers && a.papers > 0 },
    {
      label: '相关性评分（非概率）',
      render: (a) => `${Math.round(a.matchScore)}/100`,
      best: (a) => a.matchScore === maxMatch && a.matchScore > 0,
    },
  ];

  return (
    <div className={styles.container}>
      <PageCloseButton />
      <h2 className={styles.title}>导师对比</h2>
      <p className={styles.subtitle}>已选择 {advisors.length} 位导师，绿色高亮为该指标最优</p>

      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.rowLabel}>指标</th>
            {advisors.map((a) => (
              <th key={a.id} className={styles.colHeader}>
                {a.name}
                <div className={styles.colHeaderDept}>{a.department}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td className={styles.rowLabel}>{row.label}</td>
              {advisors.map((a) => (
                <td
                  key={a.id}
                  className={`${styles.cell} ${row.best?.(a) ? styles.cellBest : ''}`}
                >
                  {row.render(a)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default ComparePage;

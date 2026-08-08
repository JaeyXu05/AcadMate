import { useEffect, useMemo, useState } from 'react';
import { Spin, Empty } from 'antd';
import { BulbOutlined } from '@ant-design/icons';
import { getRecommendations } from '../services/recommend';
import type { Advisor, SortBy } from '../types/search';
import AdvisorCard from '../components/AdvisorCard';
import SortSelector from '../components/SortSelector';
import PageCloseButton from '../components/PageCloseButton';
import styles from './RecommendPage.module.css';

/** 复用检索页的排序逻辑（与 SearchPage 保持一致） */
function sortAdvisors(list: Advisor[], by: SortBy): Advisor[] {
  const sorted = [...list];
  switch (by) {
    case 'match':
      sorted.sort((a, b) => b.matchScore - a.matchScore);
      break;
    case 'staffId':
      sorted.sort((a, b) => a.id.localeCompare(b.id));
      break;
    case 'papers':
      sorted.sort((a, b) => b.papers - a.papers);
      break;
    case 'department':
      sorted.sort((a, b) => a.department.localeCompare(b.department, 'zh'));
      break;
  }
  return sorted;
}

function RecommendPage() {
  const [advisors, setAdvisors] = useState<Advisor[]>([]);
  const [basedOn, setBasedOn] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortBy>('match');
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await getRecommendations();
        if (!cancelled) {
          setAdvisors(res.recommendations);
          setBasedOn(res.basedOn);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const sorted = useMemo(() => sortAdvisors(advisors, sortBy), [advisors, sortBy]);

  return (
    <div className={styles.container}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <BulbOutlined style={{ color: '#667eea' }} />
        猜你喜欢
      </h2>
      <p className={styles.subtitle}>
        根据你的兴趣画像与学术指标，为你主动推荐可能感兴趣的导师
      </p>

      {loading ? (
        <div className={styles.loadingWrap}>
          <Spin size="large" />
        </div>
      ) : error ? (
        <div className={styles.emptyState}>
          <Empty
            description={<span style={{ color: 'rgba(255,255,255,0.45)' }}>加载推荐失败，请稍后重试</span>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      ) : (
        <>
          {basedOn.length > 0 && (
            <div className={styles.basedOn}>
              推荐依据：{basedOn.join('、')}
            </div>
          )}
          <SortSelector value={sortBy} onChange={setSortBy} />
          <div className={styles.resultsArea}>
            {sorted.length === 0 ? (
              <div className={styles.emptyState}>
                <Empty
                  description={
                    <span style={{ color: 'rgba(255,255,255,0.45)' }}>
                      暂无推荐，试试在「个人信息」补充兴趣方向
                    </span>
                  }
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            ) : (
              <div className={styles.resultsList}>
                {sorted.map((a) => (
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

export default RecommendPage;

import { useEffect, useMemo, useState } from 'react';
import { Spin, Empty } from 'antd';
import { Sparkles } from 'lucide-react';
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
          setAdvisors(res.recommendations.map((item) => ({
            ...item,
            scoreKind: item.scoreKind || res.scoreKind || 'interest_overlap',
          })));
          setBasedOn((res.basedOn || []).slice(0, 8));
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

  const sorted = useMemo(
    () => sortAdvisors(advisors, sortBy),
    [advisors, sortBy],
  );

  return (
    <div className={styles.container}>
      <PageCloseButton />
      <h2 className={styles.title}>
        <Sparkles size={16} strokeWidth={1.5} className="text-slate-600" />
        猜你喜欢
      </h2>
      <p className={styles.subtitle}>
        根据你的长期兴趣与近期检索，为你发现尚未收藏的相关导师
      </p>

      {loading ? (
        <div className={styles.loadingWrap}>
          <Spin size="large" />
        </div>
      ) : error ? (
        <div className={styles.emptyState}>
          <Empty
            description={<span className="text-stone-400">加载推荐失败，请稍后重试</span>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        </div>
      ) : (
        <>
          {basedOn.length > 0 && (
            <div className={styles.basedOn}>
              <div>推荐依据：{basedOn.join('、')}</div>
              <div className={styles.scoreNote}>推荐指数综合主题相关性、兴趣覆盖、近期检索与证据充分度；不是检索页的绝对匹配分。</div>
            </div>
          )}
          <SortSelector value={sortBy} onChange={setSortBy} />
          <div className={styles.resultsArea}>
            {sorted.length === 0 ? (
              <div className={styles.emptyState}>
                <Empty
                  description={<span className="text-stone-400">没有与当前核心画像重叠的导师</span>}
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              </div>
            ) : (
              <div className={styles.resultsList}>
                {sorted.map((a) => (
                  <AdvisorCard
                    key={a.id}
                    advisor={a}
                    onDislike={(id) => setAdvisors((prev) => prev.filter((item) => item.id !== id))}
                  />
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

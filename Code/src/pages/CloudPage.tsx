import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Empty, Spin } from 'antd';
import { getCloudData } from '../services/cloud';
import { useSearchStore } from '../stores/searchStore';
import type { CloudData, CloudNode } from '../types/cloud';
import CloudGraph from '../components/CloudGraph';
import PageCloseButton from '../components/PageCloseButton';
import Button from '../components/Button';
import styles from './CloudPage.module.css';

function CloudPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<CloudData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const d = await getCloudData();
        if (!cancelled) setData(d);
      } catch {
        if (!cancelled) setError('加载云图数据失败');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedNode: CloudNode | undefined =
    data?.nodes.find((n) => n.id === selectedId) ?? undefined;

  // 点击"在检索中查找"：用节点研究方向（或姓名）作为 query，跳检索页自动发起检索
  const handleSearchInCloud = () => {
    if (!selectedNode) return;
    const query =
      selectedNode.tags && selectedNode.tags.length > 0
        ? selectedNode.tags.join(' ')
        : selectedNode.name;
    useSearchStore.getState().setPendingQuery(query);
    navigate('/search');
  };

  return (
    <div className={styles.container}>
      <PageCloseButton />

      <div className={styles.header}>
        <h2 className={styles.title}>星云图</h2>
        <p className={styles.subtitle}>
          以研究方向为引力，探索导师之间的合作与关联网络
        </p>
      </div>

      <div className={styles.body}>
        {/* 左：云图画布 */}
        <div className={styles.canvasWrap}>
          {loading ? (
            <div className={styles.centerState}>
              <Spin size="large" tip="加载中" />
            </div>
          ) : error ? (
            <div className={styles.centerState}>
              <Empty
                description={<span style={{ color: 'rgba(255,255,255,0.45)' }}>{error}</span>}
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </div>
          ) : (
            <CloudGraph
              nodes={data?.nodes ?? []}
              edges={data?.edges ?? []}
              selectedId={selectedId ?? undefined}
              onSelectNode={setSelectedId}
              loading={loading}
            />
          )}
        </div>

        {/* 右：选中节点详情面板 */}
        <aside className={`${styles.detail} ${selectedNode ? styles.detailOpen : ''}`}>
          {selectedNode ? (
            <>
              <div className={styles.detailHeader}>
                <div className={styles.detailAvatar}>
                  {selectedNode.name.charAt(0)}
                </div>
                <div>
                  <div className={styles.detailName}>{selectedNode.name}</div>
                  <div className={styles.detailDept}>
                    {selectedNode.department ?? '—'}
                    {selectedNode.domain_name && (
                      <span className={styles.domainTag}>{selectedNode.domain_name}</span>
                    )}
                  </div>
                </div>
              </div>

              {selectedNode.tags && selectedNode.tags.length > 0 && (
                <div className={styles.tagRow}>
                  {selectedNode.tags.map((t) => (
                    <span key={t} className={styles.tag}>{t}</span>
                  ))}
                </div>
              )}

              <div className={styles.metricRow}>
                <div className={styles.metric}>
                  <div className={styles.metricLabel}>论文</div>
                  <div className={styles.metricValue}>{selectedNode.papers ?? '—'}</div>
                </div>
                {selectedNode.matchScore != null && (
                  <div className={styles.metric}>
                    <div className={styles.metricLabel}>匹配度</div>
                    <div className={styles.metricValue} style={{ color: '#52c41a' }}>
                      {selectedNode.matchScore}%
                    </div>
                  </div>
                )}
              </div>

              {selectedNode.methods && selectedNode.methods.length > 0 && (
                <div className={styles.methodRow}>
                  {selectedNode.methods.map((m) => (
                    <span key={m} className={styles.methodTag}>{m}</span>
                  ))}
                </div>
              )}

              {selectedNode.homepage && (
                <a
                  className={styles.homepageLink}
                  href={selectedNode.homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  主页
                </a>
              )}

              {selectedNode.recruitment && (
                <div className={styles.infoBlock}>
                  <div className={styles.infoLabel}>招生信息</div>
                  <p className={styles.infoText}>{selectedNode.recruitment}</p>
                </div>
              )}

              {selectedNode.pubs && selectedNode.pubs.length > 0 && (
                <div className={styles.infoBlock}>
                  <div className={styles.infoLabel}>代表论文</div>
                  <ul className={styles.pubList}>
                    {selectedNode.pubs.slice(0, 5).map((p) => (
                      <li key={p} className={styles.pubItem}>{p}</li>
                    ))}
                  </ul>
                </div>
              )}

              <Button
                variant="brand"
                size="medium"
                onClick={handleSearchInCloud}
                style={{ width: '100%', marginBottom: 12 }}
              >
                在检索中查找相关导师
              </Button>

              <p className={styles.detailHint}>
                点击空白处或右上角 ✕ 可取消选中
              </p>
            </>
          ) : (
            <div className={styles.detailEmpty}>
              <Empty
                description={
                  <span style={{ color: 'rgba(255,255,255,0.35)' }}>
                    点击图中节点查看导师详情
                  </span>
                }
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

export default CloudPage;

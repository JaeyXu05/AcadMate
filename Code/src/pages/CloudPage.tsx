import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Empty, Spin } from 'antd';
import { useNavigate } from 'react-router-dom';
import CloudGraph from '../components/CloudGraph';
import PageCloseButton from '../components/PageCloseButton';
import Button from '../components/Button';
import { getCloudData } from '../services/cloud';
import { useSearchStore } from '../stores/searchStore';
import type { CloudData, CloudNode } from '../types/cloud';
import styles from './CloudPage.module.css';

const ALL_DOMAINS = 'all';

function searchableText(node: CloudNode): string {
  return [node.name, node.department, node.domain_name, ...(node.tags ?? []), ...(node.methods ?? []), ...(node.pubs ?? [])]
    .join(' ')
    .toLocaleLowerCase();
}

function CloudPage() {
  const navigate = useNavigate();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<CloudData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeDomain, setActiveDomain] = useState(ALL_DOMAINS);
  const [query, setQuery] = useState('');
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number }>();
  const [resetSignal, setResetSignal] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getCloudData()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          const message = reason instanceof Error && reason.message
            ? `加载失败：${reason.message}`
            : '云图数据暂时无法加载';
          setError(message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const allNodes = data?.nodes ?? [];
  const visibleNodes = useMemo(
    () => allNodes.filter((node) => activeDomain === ALL_DOMAINS || node.domain === activeDomain),
    [activeDomain, allNodes],
  );
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.id)), [visibleNodes]);
  const visibleEdges = useMemo(
    () => data?.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)) ?? [],
    [data, visibleIds],
  );
  const selectedNode = allNodes.find((node) => node.id === selectedId);

  const legend = useMemo(() => {
    if (data?.meta?.legend?.length) return data.meta.legend;
    const groups = new Map<string, { id: string; name: string; color: string; count: number }>();
    for (const node of allNodes) {
      const id = node.domain ?? 'unclassified';
      const item = groups.get(id) ?? {
        id,
        name: node.domain_name ?? '待分类',
        color: node.color ?? '#a7b0c0',
        count: 0,
      };
      item.count += 1;
      groups.set(id, item);
    }
    return [...groups.values()].sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, 'zh-CN'));
  }, [allNodes, data]);

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const searchResults = useMemo(() => {
    if (!normalizedQuery) return [];
    return allNodes
      .filter((node) => searchableText(node).includes(normalizedQuery))
      .sort((left, right) => {
        const leftName = left.name.toLocaleLowerCase().includes(normalizedQuery) ? 1 : 0;
        const rightName = right.name.toLocaleLowerCase().includes(normalizedQuery) ? 1 : 0;
        return rightName - leftName || left.name.localeCompare(right.name, 'zh-CN');
      })
      .slice(0, 8);
  }, [allNodes, normalizedQuery]);

  const finishSearch = () => {
    setQuery('');
    searchInputRef.current?.blur();
  };

  const focusMentor = (node: CloudNode) => {
    if (activeDomain !== ALL_DOMAINS && node.domain !== activeDomain) setActiveDomain(ALL_DOMAINS);
    setSelectedId(node.id);
    setFocusRequest({ id: node.id, nonce: Date.now() });
    finishSearch();
  };

  const handleGraphSelect = (id: string | null) => {
    if (!id) {
      setSelectedId(null);
      return;
    }
    const mentor = allNodes.find((node) => node.id === id);
    if (mentor) focusMentor(mentor);
  };

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    if (searchResults[0]) focusMentor(searchResults[0]);
  };

  const handleDomainChange = (domain: string) => {
    setActiveDomain(domain);
    if (selectedNode && domain !== ALL_DOMAINS && selectedNode.domain !== domain) setSelectedId(null);
    setResetSignal((signal) => signal + 1);
  };

  const handleRelatedSearch = () => {
    if (!selectedNode) return;
    const relatedQuery = selectedNode.tags?.length ? selectedNode.tags.join(' ') : selectedNode.name;
    useSearchStore.getState().setPendingQuery(relatedQuery);
    navigate('/search');
  };

  const status = data?.meta?.data_status ?? 'snapshot';
  const statusLabel = status === 'ready' ? 'RAG 已同步' : status === 'stale' ? '数据需更新' : 'RAG 快照';
  const generatedAt = data?.meta?.generated_at ? new Date(data.meta.generated_at) : null;
  const generatedLabel = generatedAt && !Number.isNaN(generatedAt.valueOf())
    ? generatedAt.toLocaleDateString('zh-CN')
    : undefined;

  return (
    <div className={styles.container}>
      <PageCloseButton />
      <header className={styles.header}>
        <div>
          <div className={styles.eyebrow}>OPEN RESEARCH · MENTOR EVIDENCE LAYER</div>
          <h1 className={styles.title}>导师研究星图</h1>
          <p className={styles.subtitle}>Mission State Graph 的导师证据层：按研究方向组织导师，以同领域空间近邻解释局部关联。</p>
        </div>
        {data && (
          <div className={styles.headerMeta} aria-label="云图数据状态">
            <span className={`${styles.statusBadge} ${styles[`status_${status}`]}`}>{statusLabel}</span>
            <span>{allNodes.length} 位导师</span>
            <span>{data.meta?.evidence_count ?? 0} 条证据</span>
            {generatedLabel && <span>更新于 {generatedLabel}</span>}
          </div>
        )}
      </header>

      <main className={styles.body}>
        <section className={styles.canvasWrap} aria-label="导师研究星图探索区">
          {loading ? (
            <div className={styles.centerState} aria-live="polite">
              <Spin size="large" />
              <span>正在校验 RAG 与星图数据…</span>
            </div>
          ) : error ? (
            <div className={styles.centerState} role="alert">
              <Empty description={<span className={styles.stateText}>{error}</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              <button className={styles.retryButton} type="button" onClick={() => setReloadKey((key) => key + 1)}>重新加载</button>
            </div>
          ) : visibleNodes.length === 0 ? (
            <div className={styles.centerState}>
              <Empty description={<span className={styles.stateText}>当前领域暂无可显示导师</span>} />
              <button className={styles.retryButton} type="button" onClick={() => handleDomainChange(ALL_DOMAINS)}>查看全部领域</button>
            </div>
          ) : (
            <>
              <CloudGraph
                nodes={visibleNodes}
                edges={visibleEdges}
                selectedId={selectedId ?? undefined}
                onSelectNode={handleGraphSelect}
                focusRequest={focusRequest}
                resetSignal={resetSignal}
                labelMode="domains"
              />

              <div className={styles.toolbar}>
                <form className={styles.searchForm} onSubmit={handleSearch} role="search">
                  <label className={styles.srOnly} htmlFor="cloud-search">搜索导师、院系或研究方向</label>
                  <span className={styles.searchIcon} aria-hidden="true">⌕</span>
                  <input ref={searchInputRef} id="cloud-search" className={styles.searchInput} value={query}
                    onChange={(event) => setQuery(event.target.value)} placeholder="搜索导师、院系或研究方向" autoComplete="off" />
                  {query && (
                    <button className={styles.clearSearch} type="button" aria-label="清空搜索" onClick={() => {
                      setQuery('');
                      searchInputRef.current?.focus();
                    }}>×</button>
                  )}
                  {normalizedQuery && (
                    <div className={styles.searchResults} role="listbox" aria-label="星图搜索结果">
                      {searchResults.length ? searchResults.map((node) => (
                        <button key={node.id} type="button" role="option" onClick={() => focusMentor(node)}>
                          <span className={styles.resultDot} style={{ background: node.color }} />
                          <span><strong>{node.name}</strong><small>{node.department || '院系待补充'} · {node.domain_name || '待分类'}</small></span>
                        </button>
                      )) : <div className={styles.noResults}>没有匹配的导师或研究方向</div>}
                    </div>
                  )}
                </form>
                <button className={`${styles.toolButton} ${styles.focusButton}`} type="button"
                  disabled={!selectedNode || !visibleIds.has(selectedNode.id)} onClick={() => selectedNode && focusMentor(selectedNode)}>
                  聚焦选中
                </button>
                <button className={styles.toolButton} type="button" onClick={() => setResetSignal((signal) => signal + 1)}>重置视角</button>
              </div>

              <aside className={styles.legendPanel} aria-label="研究领域筛选">
                <div className={styles.legendHeader}><span>研究领域</span><small>{visibleNodes.length} / {allNodes.length}</small></div>
                <div className={styles.legendList}>
                  <button type="button" className={activeDomain === ALL_DOMAINS ? styles.legendActive : ''} aria-pressed={activeDomain === ALL_DOMAINS} onClick={() => handleDomainChange(ALL_DOMAINS)}>
                    <span className={`${styles.legendDot} ${styles.legendAll}`} /><span>全部领域</span><small>{allNodes.length}</small>
                  </button>
                  {legend.map((item) => (
                    <button key={item.id} type="button" className={activeDomain === item.id ? styles.legendActive : ''} aria-pressed={activeDomain === item.id} onClick={() => handleDomainChange(item.id)}>
                      <span className={styles.legendDot} style={{ background: item.color }} /><span>{item.name}</span><small>{item.count}</small>
                    </button>
                  ))}
                </div>
              </aside>

              <div className={styles.graphStats} aria-live="polite">
                <span><strong>{visibleNodes.length}</strong> 节点</span>
                <span><strong>{visibleEdges.length}</strong> 同领域近邻</span>
              </div>
              <div className={styles.instructions}>拖拽旋转 · 滚轮缩放 · 点击查看导师 · 按 0 重置</div>
            </>
          )}
        </section>

        {selectedNode && (
          <aside className={styles.detail} aria-live="polite" aria-label={`${selectedNode.name} 详情`}>
            <button className={styles.detailClose} type="button" aria-label="关闭导师详情" onClick={() => setSelectedId(null)}>×</button>
            <div className={styles.detailHeader}>
              <div className={styles.detailAvatar} style={{ background: selectedNode.color ?? '#748df0' }}>{selectedNode.name.charAt(0) || '师'}</div>
              <div className={styles.detailIdentity}><div className={styles.detailName}>{selectedNode.name || '未命名导师'}</div><div className={styles.detailDept}>{selectedNode.department || '院系待补充'}</div></div>
            </div>
            <div className={styles.domainLine}><span className={styles.resultDot} style={{ background: selectedNode.color }} />
              {selectedNode.domain_name || '待分类'}{selectedNode.classification_status === 'unclassified' && <em>资料不足</em>}
            </div>
            <div className={styles.metricRow}>
              <div className={styles.metric}><span>论文</span><strong>{selectedNode.papers ?? 0}</strong></div>
              <div className={styles.metric}><span>研究方向</span><strong>{selectedNode.tags?.length ?? 0}</strong></div>
              <div className={styles.metric}><span>近邻</span><strong>{(data?.edges ?? []).filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id).length}</strong></div>
            </div>
            {selectedNode.tags?.length ? (
              <section className={styles.detailSection}><h3>研究方向</h3><div className={styles.tagRow}>{selectedNode.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></section>
            ) : <div className={styles.missingNotice}>RAG 暂无结构化研究方向，已保留为待补充状态。</div>}
            {selectedNode.methods?.length ? (
              <section className={styles.detailSection}><h3>研究方法</h3><div className={styles.methodRow}>{selectedNode.methods.map((method) => <span key={method}>{method}</span>)}</div></section>
            ) : null}
            {selectedNode.pubs?.length ? (
              <section className={styles.detailSection}><h3>代表论文</h3><ul className={styles.pubList}>{selectedNode.pubs.slice(0, 4).map((paper) => <li key={paper}>{paper}</li>)}</ul></section>
            ) : null}
            {selectedNode.recruitment && (
              <section className={styles.detailSection}><h3>招生信息</h3><p className={styles.detailText}>{selectedNode.recruitment}</p></section>
            )}
            <div className={styles.detailActions}>
              <Button variant="brand" size="medium" onClick={handleRelatedSearch} style={{ width: '100%' }}>检索相近研究方向</Button>
              {selectedNode.homepage && <a href={selectedNode.homepage} target="_blank" rel="noopener noreferrer">查看官方主页 ↗</a>}
            </div>
          </aside>
        )}
      </main>
      {data?.meta?.warnings?.length ? <div className={styles.dataWarning} role="status">{data.meta.warnings.join('；')}</div> : null}
    </div>
  );
}

export default CloudPage;

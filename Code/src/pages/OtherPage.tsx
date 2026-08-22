import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Pagination, Spin, Modal } from 'antd';
import {
  HistoryOutlined,
  MailOutlined,
  FilePdfOutlined,
  StarOutlined,
  UserOutlined,
  BulbOutlined,
  DeleteOutlined,
  ArrowLeftOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import * as userApi from '../services/user';
import { useSearchStore } from '../stores/searchStore';
import type { HistoryItem, SearchHistoryContent, ChatHistoryContent } from '../types/auth';
import styles from './OtherPage.module.css';

// ---- 卡片入口配置 ----
interface EntryCard {
  key: string;
  icon: React.ReactNode;
  label: string;
  desc: string;
}

const CARDS: EntryCard[] = [
  {
    key: 'history',
    icon: <HistoryOutlined />,
    label: '历史记录',
    desc: '过往检索与对话记录，点击可恢复',
  },
  {
    key: 'email',
    icon: <MailOutlined />,
    label: '邮件模板',
    desc: '生成联系导师的个性化邮件，一键复制',
  },
  {
    key: 'favorites',
    icon: <StarOutlined />,
    label: '我的收藏',
    desc: '已收藏导师列表，支持对比与取消收藏',
  },
  {
    key: 'pdf',
    icon: <FilePdfOutlined />,
    label: 'PDF 分析',
    desc: '上传论文 PDF，深度分析后推荐导师',
  },
  {
    key: 'profile',
    icon: <UserOutlined />,
    label: '个人信息',
    desc: '年级、专业、兴趣方向与个人简介',
  },
  {
    key: 'recommend',
    icon: <BulbOutlined />,
    label: '猜你喜欢',
    desc: '根据你的偏好智能推荐导师',
  },
];

// ---- 视图模式 ----
type ViewMode = 'grid' | 'history';

function OtherPage() {
  const navigate = useNavigate();
  const [view, setView] = useState<ViewMode>('grid');

  // 历史记录状态
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [loading, setLoading] = useState(false);

  const loadHistory = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const data = await userApi.getHistory(p, pageSize);
      setItems(data.items);
      setTotal(data.total);
      setPage(data.page);
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  }, [pageSize]);

  // 进入历史记录面板时加载数据，返回网格时重置
  useEffect(() => {
    if (view === 'history') {
      loadHistory(1);
    }
  }, [view, loadHistory]);

  const handleCardClick = (key: string) => {
    switch (key) {
      case 'history':
        setView('history');
        break;
      case 'favorites':
        navigate('/favorites');
        break;
      case 'profile':
        navigate('/profile');
        break;
      case 'email':
        navigate('/email');
        break;
      case 'pdf':
        navigate('/pdf');
        break;
      case 'recommend':
        navigate('/recommend');
        break;
      default:
        // 其余未实现卡片暂时占位提示
        Modal.info({
          title: '即将上线',
          content: '该功能正在开发中，敬请期待。',
          centered: true,
        });
    }
  };

  const handleBack = () => {
    setView('grid');
    setItems([]);
    setTotal(0);
    setPage(1);
  };

  // 点击历史项恢复：search 用 query，chat 用首轮 user 消息，都跳检索页自动发起一次检索
  const handleResume = (item: HistoryItem) => {
    let query = '';
    if (item.type === 'search') {
      query = (item.content as SearchHistoryContent).query || '';
    } else {
      query = (item.content as ChatHistoryContent).firstMessage || '';
    }
    if (!query) return;
    useSearchStore.getState().setPendingQuery(query);
    navigate('/search');
  };

  const handleDelete = async (id: string) => {
    try {
      await userApi.deleteHistory(id);
      // 本地移除该条
      setItems((prev) => {
        const next = prev.filter((it) => it.id !== id);
        setTotal((t) => t - 1);
        return next;
      });
    } catch {
      // 静默
    }
  };

  const handleClearAll = () => {
    Modal.confirm({
      title: '清空全部历史记录',
      content: '确定清空所有检索和对话历史吗？此操作不可撤销。',
      okText: '确认清空',
      cancelText: '取消',
      okButtonProps: { danger: true },
      centered: true,
      icon: <ExclamationCircleOutlined />,
      onOk: async () => {
        try {
          await userApi.clearHistory();
          setItems([]);
          setTotal(0);
          setPage(1);
        } catch {
          // 静默
        }
      },
    });
  };

  const handlePageChange = (p: number) => {
    loadHistory(p);
  };

  const formatContent = (item: HistoryItem): string => {
    if (item.type === 'search') {
      const c = item.content as SearchHistoryContent;
      return `搜索："${c.query}" （${c.resultsCount} 个结果）`;
    }
    const c = item.content as ChatHistoryContent;
    return c.firstMessage.length > 80
      ? c.firstMessage.slice(0, 80) + '…'
      : c.firstMessage;
  };

  const formatTime = (ts: string): string => {
    try {
      // SQLite datetime 格式: "YYYY-MM-DD HH:mm:ss"
      const d = new Date(ts.replace(' ', 'T'));
      if (isNaN(d.getTime())) return ts;
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 1) return '刚刚';
      if (diffMin < 60) return `${diffMin} 分钟前`;
      const diffHour = Math.floor(diffMin / 60);
      if (diffHour < 24) return `${diffHour} 小时前`;
      const diffDay = Math.floor(diffHour / 24);
      if (diffDay < 7) return `${diffDay} 天前`;
      return ts.slice(0, 10);
    } catch {
      return ts;
    }
  };

  // ===== 卡片网格视图 =====
  if (view === 'grid') {
    return (
      <div className={styles.container}>
        <h2 style={{ color: '#fff', margin: 0, fontSize: 22 }}>其他功能</h2>
        <p style={{ color: 'rgba(255,255,255,0.35)', fontSize: 14, margin: '6px 0 0' }}>
          实用工具与个人数据，持续扩充中
        </p>
        <div className={styles.grid}>
          {CARDS.map((card) => (
            <div
              key={card.key}
              className={styles.entryCard}
              onClick={() => handleCardClick(card.key)}
            >
              <span className={styles.entryIcon}>{card.icon}</span>
              <span className={styles.entryLabel}>{card.label}</span>
              <span className={styles.entryDesc}>{card.desc}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ===== 历史记录面板视图 =====
  return (
    <div className={styles.container}>
      <div className={styles.historyPanel}>
        {/* 顶部栏 */}
        <div className={styles.historyHeader}>
          <div className={styles.historyTitle}>
            <button className={styles.backBtn} onClick={handleBack}>
              <ArrowLeftOutlined />
              返回
            </button>
            <h2>
              <HistoryOutlined style={{ marginRight: 8, color: '#667eea' }} />
              历史记录
            </h2>
          </div>
          {total > 0 && (
            <div className={styles.historyActions}>
              <button className={styles.clearAllBtn} onClick={handleClearAll}>
                <DeleteOutlined style={{ marginRight: 4 }} />
                清空全部
              </button>
            </div>
          )}
        </div>

        {/* 内容 */}
        {loading ? (
          <div className={styles.loadingWrap}>
            <Spin size="large" />
          </div>
        ) : items.length === 0 ? (
          <div className={styles.emptyWrap}>
            <HistoryOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.1)' }} />
            <span className={styles.emptyText}>暂无历史记录</span>
            <span className={styles.emptyHint}>使用检索功能后，记录会自动出现在这里</span>
          </div>
        ) : (
          <>
            <div className={styles.historyList}>
              {items.map((item) => (
                <div
                  key={item.id}
                  className={styles.historyItem}
                  onClick={() => handleResume(item)}
                  title="点击恢复"
                  style={{ cursor: 'pointer' }}
                >
                  <span
                    className={`${styles.itemType} ${
                      item.type === 'search' ? styles.itemTypeSearch : styles.itemTypeChat
                    }`}
                  >
                    {item.type === 'search' ? '搜索' : '对话'}
                  </span>
                  <div className={styles.itemBody}>
                    <div className={styles.itemContent}>{formatContent(item)}</div>
                    <div className={styles.itemMeta}>{formatTime(item.created_at)}</div>
                  </div>
                  <button
                    className={styles.itemDelete}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleResume(item);
                    }}
                    title="恢复"
                    style={{ color: 'rgba(102,126,234,0.8)' }}
                  >
                    <ReloadOutlined />
                  </button>
                  <button
                    className={styles.itemDelete}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(item.id);
                    }}
                    title="删除"
                  >
                    <DeleteOutlined />
                  </button>
                </div>
              ))}
            </div>

            {total > pageSize && (
              <div className={styles.paginationRow}>
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={total}
                  onChange={handlePageChange}
                  showSizeChanger={false}
                  size="small"
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default OtherPage;
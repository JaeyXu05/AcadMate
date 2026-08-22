import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, List, Button, Checkbox, App, Spin, Empty } from 'antd';
import { StarOutlined, DeleteOutlined, SwapOutlined } from '@ant-design/icons';
import * as userApi from '../services/user';
import { getAdvisorDetail } from '../services/advisor';
import PageCloseButton from '../components/PageCloseButton';
import type { FavoriteItem } from '../types/auth';
import type { AdvisorDetail } from '../types/advisor';

const MIN_COMPARE = 2;
const MAX_COMPARE = 4;

interface FavEntry {
  item: FavoriteItem;
  detail: AdvisorDetail | null;
}

function FavoritesPage() {
  const navigate = useNavigate();
  const [entries, setEntries] = useState<FavEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { message } = App.useApp();

  const loadFavorites = async () => {
    setLoading(true);
    try {
      const data = await userApi.getFavorites();
      // 并行取每位导师详情用于展示姓名/院系；失败降级为 null（渲染时回退到 advisor_id）
      const details = await Promise.all(
        data.map((f) => getAdvisorDetail(f.advisor_id).catch(() => null)),
      );
      setEntries(data.map((item, i) => ({ item, detail: details[i] })));
    } catch {
      message.error('加载收藏列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadFavorites();
  }, []);

  const handleRemove = async (advisorId: string) => {
    setRemoving(advisorId);
    try {
      await userApi.removeFavorite(advisorId);
      setEntries((prev) => prev.filter((e) => e.item.advisor_id !== advisorId));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(advisorId);
        return next;
      });
      message.success('已取消收藏');
    } catch {
      message.error('取消收藏失败');
    } finally {
      setRemoving(null);
    }
  };

  const toggleSelect = (advisorId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(advisorId)) {
        next.delete(advisorId);
      } else {
        if (next.size >= MAX_COMPARE) {
          message.warning(`最多对比 ${MAX_COMPARE} 位导师`);
          return prev;
        }
        next.add(advisorId);
      }
      return next;
    });
  };

  const handleCompare = () => {
    if (selected.size < MIN_COMPARE) {
      message.warning(`至少选择 ${MIN_COMPARE} 位导师`);
      return;
    }
    navigate('/compare', { state: { advisor_ids: Array.from(selected) } });
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 300 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ padding: '32px 48px', maxWidth: 1080, margin: '0 auto', flex: 1, overflowY: 'auto', width: '100%' }}>
      <PageCloseButton />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4, flexWrap: 'wrap', gap: 12 }}>
        <h2 style={{ color: '#fff', marginBottom: 0, fontSize: 24, margin: 0 }}>
          <StarOutlined style={{ marginRight: 10, color: '#667eea' }} />
          我的收藏
        </h2>
        {entries.length >= MIN_COMPARE && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 13 }}>
              已选 {selected.size}/{MAX_COMPARE}
            </span>
            <Button
              type="primary"
              icon={<SwapOutlined />}
              onClick={handleCompare}
              disabled={selected.size < MIN_COMPARE}
            >
              对比所选
            </Button>
          </div>
        )}
      </div>
      <p style={{ color: 'rgba(255,255,255,0.45)', fontSize: 14, margin: '6px 0 28px' }}>
        共 {entries.length} 位导师 · 勾选 {MIN_COMPARE}~{MAX_COMPARE} 位可对比，点击卡片查看详情
      </p>

      {entries.length === 0 ? (
        <Card
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.06)',
            textAlign: 'center',
            padding: 48,
          }}
        >
          <Empty
            description={<span style={{ color: 'rgba(255,255,255,0.45)' }}>还没有收藏任何导师</span>}
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
          <p style={{ color: 'rgba(255,255,255,0.35)', marginTop: 12 }}>
            在检索页找到感兴趣的导师后，点击 ⭐ 即可收藏
          </p>
        </Card>
      ) : (
        <List
          dataSource={entries}
          split={false}
          renderItem={({ item, detail }) => {
            const checked = selected.has(item.advisor_id);
            const displayName = detail?.name ?? `导师 ID：${item.advisor_id}`;
            const avatarChar = (detail?.name ?? item.advisor_id ?? '?').charAt(0).toUpperCase();
            return (
              <List.Item
                style={{
                  background: checked ? 'rgba(102,126,234,0.1)' : 'rgba(255,255,255,0.04)',
                  border: checked ? '1px solid rgba(102,126,234,0.4)' : '1px solid rgba(255,255,255,0.06)',
                  borderRadius: 10,
                  padding: '20px 24px',
                  marginBottom: 14,
                  transition: 'background 0.2s, border-color 0.2s',
                  cursor: 'pointer',
                }}
                onClick={() => navigate(`/advisor/${encodeURIComponent(item.advisor_id)}`)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, width: '100%' }}>
                  {/* 复选框（阻止冒泡，避免点选时跳详情） */}
                  <Checkbox
                    checked={checked}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => toggleSelect(item.advisor_id)}
                    style={{ flexShrink: 0 }}
                  />
                  <List.Item.Meta
                    avatar={
                      <div
                        style={{
                          width: 44,
                          height: 44,
                          borderRadius: 10,
                          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: '#fff',
                          fontSize: 18,
                          fontWeight: 600,
                          flexShrink: 0,
                        }}
                      >
                        {avatarChar}
                      </div>
                    }
                    title={
                      <span style={{ color: '#e8e8e8', fontSize: 16, fontWeight: 500 }}>
                        {displayName}
                        {detail?.title && (
                          <span style={{ color: 'rgba(255,255,255,0.5)', fontSize: 13, fontWeight: 400, marginLeft: 8 }}>
                            {detail.title}
                          </span>
                        )}
                      </span>
                    }
                    description={
                      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 13 }}>
                        {detail ? `${detail.department} · 收藏于 ${item.created_at}` : `收藏于 ${item.created_at}`}
                      </span>
                    }
                  />
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    loading={removing === item.advisor_id}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRemove(item.advisor_id);
                    }}
                  >
                    取消收藏
                  </Button>
                </div>
              </List.Item>
            );
          }}
        />
      )}
    </div>
  );
}

export default FavoritesPage;

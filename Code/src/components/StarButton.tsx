import { useState, useEffect } from 'react';
import { App } from 'antd';
import { StarOutlined, StarFilled } from '@ant-design/icons';
import * as userApi from '../services/user';

interface StarButtonProps {
  advisorId: string;
  /** 受控初值：是否已收藏。不传则内部自管，挂载时向后端查初始收藏状态 */
  favorited?: boolean;
  /** 收藏状态变化回调（受控/非受控都会触发） */
  onToggle?: (favorited: boolean) => void;
  /** 按钮样式变体：card=检索卡片内的小按钮，detail=详情页的大按钮 */
  variant?: 'card' | 'detail';
}

/**
 * 收藏按钮（通用）。
 * 抽自 AdvisorCard，供 AdvisorCard 与 AdvisorDetailPage 共用。
 * 非受控：内部维护 favorited 状态，挂载时查后端收藏列表初始化，避免已收藏导师显示为未收藏导致 409。
 * 受控：外部传 favorited，仅触发 onToggle，状态由外部管理（此处仍调后端 API）。
 */
function StarButton({ advisorId, favorited, onToggle, variant = 'card' }: StarButtonProps) {
  const [internalFav, setInternalFav] = useState(false);
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();

  const isControlled = favorited !== undefined;
  const isFavorited = isControlled ? favorited : internalFav;

  // 非受控模式下，挂载时查后端确认初始收藏状态
  useEffect(() => {
    if (isControlled) return;
    let cancelled = false;
    userApi
      .getFavorites()
      .then((favs) => {
        if (!cancelled) setInternalFav(favs.some((f) => f.advisor_id === advisorId));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [advisorId, isControlled]);

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (loading) return;
    setLoading(true);
    try {
      if (isFavorited) {
        await userApi.removeFavorite(advisorId);
        if (!isControlled) setInternalFav(false);
        onToggle?.(false);
        message.success('已取消收藏');
      } else {
        await userApi.addFavorite(advisorId);
        if (!isControlled) setInternalFav(true);
        onToggle?.(true);
        message.success('已收藏');
      }
    } catch {
      message.error('操作失败');
    } finally {
      setLoading(false);
    }
  };

  if (variant === 'detail') {
    return (
      <button
        onClick={handleToggle}
        disabled={loading}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 18px',
          borderRadius: 8,
          border: '1px solid rgba(255,255,255,0.12)',
          background: isFavorited ? 'rgba(250,140,22,0.12)' : 'transparent',
          color: isFavorited ? '#fa8c16' : 'rgba(255,255,255,0.75)',
          fontSize: 14,
          cursor: loading ? 'not-allowed' : 'pointer',
          opacity: loading ? 0.6 : 1,
        }}
      >
        {isFavorited ? <StarFilled /> : <StarOutlined />}
        {isFavorited ? '已收藏' : '收藏'}
      </button>
    );
  }

  // card 变体：沿用 AdvisorCard 原 actionBtn 视觉
  return (
    <button
      onClick={handleToggle}
      disabled={loading}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '5px 12px',
        borderRadius: 6,
        border: '1px solid rgba(255,255,255,0.12)',
        background: 'transparent',
        color: 'rgba(255,255,255,0.55)',
        fontSize: 13,
        cursor: loading ? 'not-allowed' : 'pointer',
        opacity: loading ? 0.6 : 1,
      }}
    >
      {isFavorited ? <StarFilled style={{ color: '#fa8c16' }} /> : <StarOutlined />}
      {isFavorited ? '已收藏' : '收藏'}
    </button>
  );
}

export default StarButton;

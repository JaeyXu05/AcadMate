import { useState, useEffect } from 'react';
import { App } from 'antd';
import { Star } from 'lucide-react';
import * as userApi from '../services/user';

interface StarButtonProps {
  advisorId: string;
  favorited?: boolean;
  onToggle?: (favorited: boolean) => void;
  variant?: 'card' | 'detail';
}

function StarButton({ advisorId, favorited, onToggle, variant = 'card' }: StarButtonProps) {
  const [internalFav, setInternalFav] = useState(false);
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();

  const isControlled = favorited !== undefined;
  const isFavorited = isControlled ? favorited : internalFav;

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

  return (
    <button
      onClick={handleToggle}
      disabled={loading}
      className={[
        'inline-flex items-center gap-1 text-[12.5px] disabled:opacity-50',
        isFavorited ? 'text-stone-800' : 'text-stone-400 hover:text-stone-700',
        variant === 'detail' ? 'border border-stone-200 px-3 py-1.5' : '',
      ].join(' ')}
    >
      <Star size={14} strokeWidth={1.5} className="text-slate-600" fill={isFavorited ? 'currentColor' : 'none'} />
      {isFavorited ? '已收藏' : '收藏'}
    </button>
  );
}

export default StarButton;

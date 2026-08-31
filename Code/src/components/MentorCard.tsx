import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { App } from 'antd';
import { Ban } from 'lucide-react';
import type { Advisor } from '../types/search';
import StarButton from './StarButton';
import { dislikeAdvisor } from '../services/feedback';

interface MentorCardProps {
  advisor: Advisor;
  compact?: boolean;
  featured?: boolean;
  onDislike?: (advisorId: string) => void;
}

function firstSentence(text?: string): string {
  if (!text) return '';
  const trimmed = text.replace(/\s+/g, ' ').trim();
  const cut = trimmed.split(/(?<=[。！？.!?])\s/)[0];
  return cut.length > 140 ? `${cut.slice(0, 140)}…` : cut;
}

function MentorCard({ advisor, compact = false, featured = false, onDislike }: MentorCardProps) {
  const navigate = useNavigate();
  const score = Number(advisor.matchScore);
  const hasScore = Number.isFinite(score) && score > 0;
  const scorePercent = hasScore ? Math.max(0, Math.min(100, Math.round(score))) : null;
  const tags = (advisor.tags ?? []).filter(Boolean).slice(0, 4);
  const reason = firstSentence(advisor.explanation);
  const initial = (advisor.name || '?').charAt(0);

  const openDetail = () => {
    navigate(`/advisor/${encodeURIComponent(advisor.id)}`);
  };

  return (
    <article
      className={[
        'solid-card cursor-pointer rounded-xl transition-transform duration-150 hover:-translate-y-0.5',
        compact ? 'px-5 py-4' : 'px-7 py-6',
      ].join(' ')}
      onClick={openDetail}
    >
      {featured && (
        <div className="mb-3 font-mono text-[10px] tracking-[0.22em] text-stone-400">
          TOP MATCH
        </div>
      )}

      <div className="flex gap-6">
        {scorePercent != null && (
          <div className="w-[72px] shrink-0 pt-0.5">
            <div className="font-mono text-[10px] tracking-[0.16em] text-stone-400">
              MATCH
            </div>
            <div className="mt-1 font-light leading-none text-stone-900" style={{ fontSize: compact ? 28 : 36 }}>
              {scorePercent}
            </div>
            <div className="mt-3 h-[2px] w-full bg-stone-100">
              <div
                className="h-[2px] bg-stone-800"
                style={{ width: `${scorePercent}%` }}
              />
            </div>
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 className="text-[18px] font-medium tracking-tight text-stone-900">
                  {advisor.name}
                </h3>
                {advisor.title && (
                  <span className="text-[13px] text-stone-500">{advisor.title}</span>
                )}
              </div>
              <div className="mt-1 text-[13px] text-stone-400">{advisor.department}</div>
            </div>
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-stone-200 bg-stone-50 text-sm font-medium text-stone-600">
              {initial}
            </div>
          </div>

          {tags.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="border border-stone-200 px-2 py-0.5 text-[11px] text-stone-500"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

          {reason && (
            <p className="mt-3 text-[13.5px] leading-relaxed text-stone-600">
              {reason}
            </p>
          )}

          <div
            className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-stone-400"
            onClick={(e) => e.stopPropagation()}
          >
            <span>论文 {advisor.papers}</span>
            <button
              type="button"
              className="text-stone-500 underline-offset-4 hover:text-stone-800 hover:underline"
              onClick={openDetail}
            >
              详情
            </button>
            <StarButton advisorId={advisor.id} variant="card" />
            {onDislike && (
              <DislikeButton advisorId={advisor.id} onDisliked={onDislike} />
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function DislikeButton({
  advisorId,
  onDisliked,
}: {
  advisorId: string;
  onDisliked: (advisorId: string) => void;
}) {
  const [loading, setLoading] = useState(false);
  const { message } = App.useApp();

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (loading) return;
    setLoading(true);
    try {
      await dislikeAdvisor(advisorId);
      message.success('已标记不感兴趣，下次推荐将避开这位导师');
      onDisliked(advisorId);
    } catch {
      message.error('操作失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className="inline-flex items-center gap-1 text-stone-400 hover:text-stone-700 disabled:opacity-50"
    >
      <Ban size={13} strokeWidth={1.5} className="text-slate-600" />
      不感兴趣
    </button>
  );
}

export default MentorCard;

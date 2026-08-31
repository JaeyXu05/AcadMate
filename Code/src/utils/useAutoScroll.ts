import { useEffect, useRef } from 'react';

const NEAR_BOTTOM_PX = 96;

/** 新内容到来时滚到容器底部；用户上翻阅读时不抢滚动。 */
export function useAutoScroll(deps: unknown[]) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const pinRef = useRef(true);

  const onScroll = () => {
    const el = scrollerRef.current;
    if (!el) return;
    pinRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
  };

  useEffect(() => {
    if (!pinRef.current) return;
    const id = requestAnimationFrame(() => {
      const el = scrollerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
      else endRef.current?.scrollIntoView({ block: 'end' });
    });
    return () => cancelAnimationFrame(id);
  }, deps);

  return { scrollerRef, endRef, onScroll };
}

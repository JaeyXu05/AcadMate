import { useCallback, useRef, useState } from 'react';

interface ResizableSplitProps {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultRatio?: number;   // 左侧占比，0-1，默认 0.45
  minRatio?: number;
  maxRatio?: number;
  /** 受控模式：外部传入当前 ratio */
  ratio?: number;
  /** 受控模式：ratio 变化回调 */
  onRatioChange?: (ratio: number) => void;
}

/**
 * 可拖拽分栏容器。
 * 左右两个面板 + 中间拖拽手柄，支持鼠标拖拽调节比例。
 */
function ResizableSplit({
  left,
  right,
  defaultRatio = 0.45,
  minRatio = 0.3,
  maxRatio = 0.7,
  ratio: controlledRatio,
  onRatioChange,
}: ResizableSplitProps) {
  const [localRatio, setLocalRatio] = useState(defaultRatio);
  const isControlled = controlledRatio !== undefined;
  const ratio = isControlled ? controlledRatio : localRatio;
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      let r = (ev.clientX - rect.left) / rect.width;
      r = Math.max(minRatio, Math.min(maxRatio, r));
      if (isControlled) {
        onRatioChange?.(r);
      } else {
        setLocalRatio(r);
      }
    };

    const onMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [minRatio, maxRatio, isControlled, onRatioChange]);

  return (
    <div
      ref={containerRef}
      style={{
        display: 'flex',
        flex: 1,
        overflow: 'hidden',
        minHeight: 0,
      }}
    >
      <div style={{ width: `${ratio * 100}%`, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {left}
      </div>

      {/* drag handle */}
      <div
        onMouseDown={onMouseDown}
        style={{
          width: 4,
          flexShrink: 0,
          cursor: 'col-resize',
          background: 'rgba(255,255,255,0.08)',
          transition: 'background 0.15s',
        }}
        onMouseEnter={(e) => {
          (e.target as HTMLElement).style.background = 'rgba(102,126,234,0.4)';
        }}
        onMouseLeave={(e) => {
          (e.target as HTMLElement).style.background = 'rgba(255,255,255,0.08)';
        }}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {right}
      </div>
    </div>
  );
}

export default ResizableSplit;
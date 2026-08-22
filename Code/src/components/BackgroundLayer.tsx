import type { ReactNode } from 'react';
import styles from './BackgroundLayer.module.css';

interface BackgroundLayerProps {
  /** 子组件作为背景内容，传纯黑色 div 则为默认背景 */
  children?: ReactNode;
}

/**
 * 可插拔背景容器
 * 默认渲染一个带缓慢呼吸/漂移的星辰渐变背景（欢迎页等品牌场景）；
 * 云图等自定义背景场景直接传 children 覆盖。
 */
function BackgroundLayer({ children }: BackgroundLayerProps) {
  if (children) {
    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 0,
          overflow: 'hidden',
        }}
      >
        {children}
      </div>
    );
  }

  return (
    <div
      className={styles.wrap}
      aria-hidden
    >
      {/* 深空本位底色 */}
      <div className={styles.base} />
      {/* 缓慢呼吸的品牌光晕（紫/蓝） */}
      <div className={styles.glowA} />
      <div className={styles.glowB} />
      {/* 悬浮随机星点（纯 CSS 动画，无重 GPU 开销） */}
      <div className={styles.stars} />
    </div>
  );
}

export default BackgroundLayer;
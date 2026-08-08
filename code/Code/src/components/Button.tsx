import type { ButtonHTMLAttributes, ReactNode } from 'react';
import styles from './Button.module.css';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** 变体：brand（品牌渐变默认）、ghost（描边）、text（透明文字） */
  variant?: 'brand' | 'ghost' | 'text';
  /** 尺寸 */
  size?: 'small' | 'medium' | 'large';
  children: ReactNode;
}

/**
 * 统一按钮组件（设计系统）。
 * 替代页面里各处手写 `linear-gradient` 渐变按钮；样式来自 Button.module.css，
 * 颜色/圆角/阴影统一引用 index.css 的 CSS 变量令牌，改设计只需动令牌。
 */
function Button({
  variant = 'brand',
  size = 'medium',
  className,
  style,
  children,
  ...rest
}: ButtonProps) {
  const cls = [styles.btn, styles[variant], styles[size], className]
    .filter(Boolean)
    .join(' ');
  return (
    <button className={cls} style={style} {...rest}>
      {children}
    </button>
  );
}

export default Button;
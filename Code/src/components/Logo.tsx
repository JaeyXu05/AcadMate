/**
 * Logo 组件
 * 当前渲染纯文字，后续替换为图片只需改为 <img> 标签
 */
interface LogoProps {
  size?: 'small' | 'default' | 'large';
}

function Logo({ size = 'default' }: LogoProps) {
  const fontSize = size === 'small' ? 16 : size === 'large' ? 34 : 20;

  return (
    <span
      style={{
        fontSize,
        fontWeight: 600,
        color: '#fff',
        letterSpacing: 1,
        userSelect: 'none',
        whiteSpace: 'nowrap',
      }}
    >
      科研导师推荐平台
    </span>
  );
}

export default Logo;
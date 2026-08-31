interface LogoProps {
  size?: 'small' | 'default' | 'large';
}

function Logo({ size = 'default' }: LogoProps) {
  const fontSize = size === 'small' ? 15 : size === 'large' ? 28 : 16;

  return (
    <span
      className="select-none whitespace-nowrap font-medium tracking-tight text-stone-900"
      style={{ fontSize }}
    >
      科研导师推荐平台
    </span>
  );
}

export default Logo;

interface ReasoningChainProps {
  text: string;
}

/**
 * 可折叠推理链面板。
 * 将文本按换行拆分，每条一步，显示序号。
 */
function ReasoningChain({ text }: ReasoningChainProps) {
  const steps = text.split('\n').filter((line) => line.trim());

  if (steps.length === 0) return null;

  return (
    <div
      style={{
        marginTop: 10,
        padding: '12px 16px',
        borderRadius: 8,
        background: 'rgba(102, 126, 234, 0.06)',
        border: '1px solid rgba(102, 126, 234, 0.12)',
      }}
    >
      {steps.map((step, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            gap: 8,
            padding: '4px 0',
            fontSize: 13,
            lineHeight: 1.6,
            color: 'rgba(255, 255, 255, 0.65)',
          }}
        >
          <span style={{ color: '#667eea', flexShrink: 0, fontWeight: 600 }}>
            {i + 1}.
          </span>
          <span>{step}</span>
        </div>
      ))}
    </div>
  );
}

export default ReasoningChain;
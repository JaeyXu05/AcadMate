interface ReasoningChainProps {
  text: string;
}

function ReasoningChain({ text }: ReasoningChainProps) {
  const steps = text.split('\n').filter((line) => line.trim());

  if (steps.length === 0) return null;

  return (
    <div className="mt-2 space-y-1.5">
      {steps.map((step, i) => (
        <div key={i} className="flex gap-2 text-[13px] leading-relaxed text-stone-600">
          <span className="w-5 shrink-0 font-mono text-[10px] text-stone-400">
            {String(i + 1).padStart(2, '0')}
          </span>
          <span>{step}</span>
        </div>
      ))}
    </div>
  );
}

export default ReasoningChain;

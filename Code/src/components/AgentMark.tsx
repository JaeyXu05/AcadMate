import type { LucideIcon } from 'lucide-react';

interface AgentMarkProps {
  Icon?: LucideIcon;
  index?: string | number;
}

function AgentMark({ Icon, index }: AgentMarkProps) {
  return (
    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-indigo-100 text-xs text-indigo-500">
      {Icon ? <Icon size={14} strokeWidth={1.5} className="text-indigo-500" /> : index}
    </span>
  );
}

export default AgentMark;

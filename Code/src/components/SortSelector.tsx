import type { SortBy } from '../types/search';

interface SortSelectorProps {
  value: SortBy;
  onChange: (sort: SortBy) => void;
}

const OPTIONS: { label: string; value: SortBy }[] = [
  { label: '研究方向匹配', value: 'match' },
  { label: '工号', value: 'staffId' },
  { label: '论文数', value: 'papers' },
  { label: '院系', value: 'department' },
];

function SortSelector({ value, onChange }: SortSelectorProps) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
      <span className="text-[12px] text-stone-400">排序</span>
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={[
            'rounded px-1.5 pb-0.5 text-[13px] transition-colors hover:bg-slate-50',
            value === opt.value
              ? 'border-b border-stone-800 font-medium text-stone-900'
              : 'border-b border-transparent text-stone-400 hover:text-stone-700',
          ].join(' ')}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default SortSelector;

import { Radio } from 'antd';
import type { SortBy } from '../types/search';

interface SortSelectorProps {
  value: SortBy;
  onChange: (sort: SortBy) => void;
}

const OPTIONS: { label: string; value: SortBy }[] = [
  { label: '匹配度', value: 'match' },
  { label: '工号', value: 'staffId' },
  { label: '论文数', value: 'papers' },
  { label: '院系', value: 'department' },
];

function SortSelector({ value, onChange }: SortSelectorProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 20px',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 13, flexShrink: 0 }}>
        排序方式
      </span>
      <Radio.Group
        value={value}
        onChange={(e) => onChange(e.target.value as SortBy)}
        size="small"
      >
        {OPTIONS.map((opt) => (
          <Radio.Button key={opt.value} value={opt.value}>
            {opt.label}
          </Radio.Button>
        ))}
      </Radio.Group>
    </div>
  );
}

export default SortSelector;
import type { LibrarySort } from '@/services/api';

interface SortSelectorProps {
  value: LibrarySort;
  onChange: (value: LibrarySort) => void;
}

const sortOptions: { value: LibrarySort; label: string }[] = [
  { value: 'last_opened_at_desc', label: '最近打开' },
  { value: 'created_at_desc', label: '上传时间' },
  { value: 'name_asc', label: '书名' },
];

export default function SortSelector({ value, onChange }: SortSelectorProps) {
  return (
    <div className="flex items-center bg-stone-100 rounded-lg p-1">
      {sortOptions.map((option) => (
        <button
          key={option.value}
          onClick={() => onChange(option.value)}
          className={`whitespace-nowrap px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer ${
            value === option.value
              ? 'bg-white text-stone-700 shadow-sm'
              : 'text-stone-400 hover:text-stone-600'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

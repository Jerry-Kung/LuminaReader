type SortOption = 'last_opened' | 'upload_time' | 'title';

interface SortSelectorProps {
  value: SortOption;
  onChange: (value: SortOption) => void;
}

const sortOptions: { value: SortOption; label: string }[] = [
  { value: 'last_opened', label: 'Last opened' },
  { value: 'upload_time', label: 'Upload time' },
  { value: 'title', label: 'Title' },
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
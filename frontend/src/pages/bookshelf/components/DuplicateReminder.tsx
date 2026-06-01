import { generateCoverColor, generateCoverPattern, formatFileSize } from '../cover';
import type { ConflictExisting } from '@/services/api';

interface DuplicateReminderProps {
  existingBook: ConflictExisting;
  onOpenExisting: () => void;
  onCreateNew: () => void;
  onCancel: () => void;
}

export default function DuplicateReminder({ existingBook, onOpenExisting, onCreateNew, onCancel }: DuplicateReminderProps) {
  const coverColor = generateCoverColor(existingBook.name);
  const coverPattern = generateCoverPattern(existingBook.name);
  const firstLetter = (existingBook.name || '?').charAt(0).toUpperCase();

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 w-full max-w-lg mx-4">
      <div className="bg-white rounded-xl shadow-lg border border-stone-200 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="relative w-10 h-14 rounded-md overflow-hidden flex-shrink-0" style={{ backgroundColor: coverColor }}>
            <div className="absolute inset-0" style={{ background: coverPattern }} />
            <div className="absolute left-0 top-0 bottom-0 w-1 bg-black/5" />
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-lg font-serif font-bold text-black/20">{firstLetter}</span>
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs text-stone-400 mb-0.5">这本书已经在你的书架里了</p>
            <h4 className="text-sm font-medium text-stone-700 truncate" title={existingBook.name}>
              {existingBook.name}
            </h4>
            <p className="text-xs text-stone-400">{formatFileSize(existingBook.primary_pdf_size)}</p>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={onOpenExisting}
              className="whitespace-nowrap px-3 py-1.5 text-xs font-medium text-amber-700 bg-amber-50 rounded-md hover:bg-amber-100 cursor-pointer transition-colors"
            >
              打开既有版本
            </button>
            <button
              onClick={onCreateNew}
              className="whitespace-nowrap px-3 py-1.5 text-xs font-medium text-stone-500 hover:text-stone-700 bg-stone-100 rounded-md hover:bg-stone-200 cursor-pointer transition-colors"
            >
              新建一份
            </button>
            <button
              onClick={onCancel}
              className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-100 cursor-pointer transition-colors"
            >
              <i className="ri-close-line text-sm"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

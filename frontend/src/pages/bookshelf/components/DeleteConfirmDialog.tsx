import { generateCoverColor, generateCoverPattern, formatFileSize } from '../cover';
import type { LibraryItem } from '@/services/api';

interface DeleteConfirmDialogProps {
  book: LibraryItem;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function DeleteConfirmDialog({ book, onConfirm, onCancel }: DeleteConfirmDialogProps) {
  const coverColor = generateCoverColor(book.name);
  const coverPattern = generateCoverPattern(book.name);
  const firstLetter = (book.name || '?').charAt(0).toUpperCase();

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="bg-white rounded-xl shadow-xl border border-stone-200 w-full max-w-sm mx-4 overflow-hidden">
        <div className="p-5">
          <div className="flex items-start gap-3">
            <div className="relative w-12 h-16 rounded-md overflow-hidden flex-shrink-0" style={{ backgroundColor: coverColor }}>
              <div className="absolute inset-0" style={{ background: coverPattern }} />
              <div className="absolute left-0 top-0 bottom-0 w-1.5 bg-black/5" />
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-xl font-serif font-bold text-black/20">{firstLetter}</span>
              </div>
            </div>
            <div>
              <h3 className="text-sm font-medium text-stone-700 mb-1">
                删除《{book.name}》及其全部对话？
              </h3>
              <p className="text-xs text-stone-400 leading-relaxed">
                这本书的截图与提问历史都会被一起清掉。
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-stone-400 mt-3 ml-[60px]">
            <span>{formatFileSize(book.primary_pdf_size)}</span>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 bg-stone-50 border-t border-stone-100">
          <button
            onClick={onCancel}
            className="whitespace-nowrap px-4 py-2 text-sm font-medium text-stone-500 hover:text-stone-700 hover:bg-stone-100 rounded-md cursor-pointer transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="whitespace-nowrap px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-md cursor-pointer transition-colors"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}

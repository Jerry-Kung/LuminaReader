import { generateCoverColor, generateCoverPattern, formatFileSize } from '@/mocks/bookshelf';
import type { Book } from '@/services/api';

interface DeleteConfirmDialogProps {
  book: Book;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function DeleteConfirmDialog({ book, onConfirm, onCancel }: DeleteConfirmDialogProps) {
  const coverColor = generateCoverColor(book.title);
  const coverPattern = generateCoverPattern(book.title);
  const firstLetter = book.title.charAt(0).toUpperCase();

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
                Delete "{book.title}"?
              </h3>
              <p className="text-xs text-stone-400 leading-relaxed">
                This book and all its conversations will be permanently removed.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-stone-400 mt-3 ml-[60px]">
            <span>{formatFileSize(book.file_size)}</span>
            <span>&middot;</span>
            <span>{book.page_count} pages</span>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-3 bg-stone-50 border-t border-stone-100">
          <button
            onClick={onCancel}
            className="whitespace-nowrap px-4 py-2 text-sm font-medium text-stone-500 hover:text-stone-700 hover:bg-stone-100 rounded-md cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="whitespace-nowrap px-4 py-2 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-md cursor-pointer transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
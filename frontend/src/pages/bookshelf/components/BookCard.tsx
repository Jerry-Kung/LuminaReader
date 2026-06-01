import { useState, useRef, useEffect } from 'react';
import type { LibraryItem } from '@/services/api';
import { formatFileSize, formatTimeAgo, generateCoverColor, generateCoverPattern } from '../cover';

interface BookCardProps {
  book: LibraryItem;
  onOpen: (book: LibraryItem) => void;
  onDelete: (book: LibraryItem) => void;
}

export default function BookCard({ book, onOpen, onDelete }: BookCardProps) {
  const [showMenu, setShowMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const coverColor = generateCoverColor(book.name);
  const coverPattern = generateCoverPattern(book.name);
  const firstLetter = (book.name || '?').charAt(0).toUpperCase();

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target as Node) &&
        buttonRef.current && !buttonRef.current.contains(e.target as Node)
      ) {
        setShowMenu(false);
      }
    };
    if (showMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showMenu]);

  const handleOpen = () => {
    setShowMenu(false);
    onOpen(book);
  };

  const handleDelete = () => {
    setShowMenu(false);
    onDelete(book);
  };

  return (
    <div className="group relative flex flex-col">
      <button
        onClick={handleOpen}
        className="relative w-full aspect-[3/4] rounded-lg overflow-hidden cursor-pointer transition-transform duration-200 hover:scale-[1.02] focus:outline-none"
        style={{ backgroundColor: coverColor }}
      >
        <div className="absolute inset-0" style={{ background: coverPattern }} />
        <div className="absolute left-0 top-0 bottom-0 w-2 bg-black/5" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-6xl font-serif font-bold text-black/20 select-none">
            {firstLetter}
          </span>
        </div>
        <div className="absolute bottom-3 right-3 w-6 h-6 flex items-center justify-center rounded bg-white/60 backdrop-blur-sm">
          <i className="ri-file-pdf-line text-stone-600 text-xs"></i>
        </div>
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/5 transition-colors duration-200" />
      </button>

      <div className="absolute top-2 right-2">
        <button
          ref={buttonRef}
          onClick={(e) => {
            e.stopPropagation();
            setShowMenu((prev) => !prev);
          }}
          className="w-7 h-7 flex items-center justify-center rounded-md bg-white/80 backdrop-blur-sm text-stone-500 hover:text-stone-700 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
        >
          <i className="ri-more-2-fill text-sm"></i>
        </button>
        {showMenu && (
          <div
            ref={menuRef}
            className="absolute top-full right-0 mt-1 w-36 bg-white rounded-lg shadow-lg border border-stone-200 py-1 z-10"
          >
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDelete();
              }}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-red-50 cursor-pointer transition-colors"
            >
              <i className="ri-delete-bin-line text-xs"></i>
              删除这本书
            </button>
          </div>
        )}
      </div>

      <div className="mt-2.5 px-0.5">
        <button
          onClick={handleOpen}
          className="w-full text-left cursor-pointer focus:outline-none"
        >
          <h3 className="text-sm font-medium text-stone-700 truncate leading-tight" title={book.name}>
            {book.name}
          </h3>
        </button>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-xs text-stone-400">{formatFileSize(book.primary_pdf_size)}</span>
          <span className="text-xs text-stone-300">&middot;</span>
          <span className="text-xs text-stone-400">{formatTimeAgo(book.last_opened_at)}</span>
        </div>
      </div>
    </div>
  );
}

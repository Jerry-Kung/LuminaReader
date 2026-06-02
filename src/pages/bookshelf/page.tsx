import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { listBooks, uploadBook, deleteBook } from '@/services/api';
import type { Book, UploadProgress } from '@/services/api';
import BookCard from './components/BookCard';
import UploadArea from './components/UploadArea';
import EmptyState from './components/EmptyState';
import SortSelector from './components/SortSelector';
import DeleteConfirmDialog from './components/DeleteConfirmDialog';
import DuplicateReminder from './components/DuplicateReminder';

export default function BookshelfPage() {
  const navigate = useNavigate();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'last_opened' | 'upload_time' | 'title'>('last_opened');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicateBook, setDuplicateBook] = useState<Book | null>(null);
  const [pendingUploadFile, setPendingUploadFile] = useState<File | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Book | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const abortRef = useRef(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadBooks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listBooks();
      setBooks(data);
    } catch {
      setBooks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBooks();
  }, [loadBooks]);

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const sortedBooks = [...books].sort((a, b) => {
    if (sortBy === 'last_opened') {
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    }
    if (sortBy === 'upload_time') {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    }
    return a.title.localeCompare(b.title);
  });

  const handleOpenBook = useCallback((book: Book) => {
    navigate(`/reader/${book.id}`);
  }, [navigate]);

  const handleUpload = useCallback(async (file: File) => {
    if (isUploading) return;
    setUploadError(null);
    setDuplicateBook(null);
    setPendingUploadFile(null);
    abortRef.current = false;
    setIsUploading(true);
    setUploadProgress({ loaded: 0, total: file.size, percentage: 0 });

    try {
      const result = await uploadBook(
        file,
        (progress) => {
          if (!abortRef.current) {
            setUploadProgress(progress);
          }
        },
      );

      if (abortRef.current) return;

      if (result.isDuplicate) {
        setDuplicateBook(result.existingBook);
        setPendingUploadFile(file);
        setIsUploading(false);
        setUploadProgress(null);
        return;
      }

      setBooks((prev) => [result.book, ...prev]);
      setIsUploading(false);
      setUploadProgress(null);
      showToast('Book uploaded successfully');
      // Auto open the new book
      setTimeout(() => {
        navigate(`/reader/${result.book.id}`);
      }, 600);
    } catch (err: any) {
      if (!abortRef.current) {
        setUploadError(err.message || 'Upload failed. Please try again.');
        setIsUploading(false);
        setUploadProgress(null);
      }
    }
  }, [isUploading, showToast]);

  const handleUploadCancel = useCallback(() => {
    abortRef.current = true;
    setIsUploading(false);
    setUploadProgress(null);
  }, []);

  const handleRetryUpload = useCallback(() => {
    if (pendingUploadFile) {
      handleUpload(pendingUploadFile);
    }
  }, [pendingUploadFile, handleUpload]);

  const handleDuplicateOpenExisting = useCallback(() => {
    if (duplicateBook) {
      navigate(`/reader/${duplicateBook.id}`);
    }
    setDuplicateBook(null);
    setPendingUploadFile(null);
  }, [duplicateBook, navigate]);

  const handleDuplicateCreateNew = useCallback(async () => {
    if (!pendingUploadFile) return;
    const file = pendingUploadFile;
    setDuplicateBook(null);
    setPendingUploadFile(null);
    setIsUploading(true);
    setUploadProgress({ loaded: 0, total: file.size, percentage: 0 });

    try {
      const result = await uploadBook(
        file,
        (progress) => {
          if (!abortRef.current) setUploadProgress(progress);
        },
        true,
      );

      if (abortRef.current) return;

      setBooks((prev) => [result.book, ...prev]);
      setIsUploading(false);
      setUploadProgress(null);
      showToast('Book uploaded successfully');
      setTimeout(() => {
        navigate(`/reader/${result.book.id}`);
      }, 600);
    } catch (err: any) {
      if (!abortRef.current) {
        setUploadError(err.message || 'Upload failed. Please try again.');
        setIsUploading(false);
        setUploadProgress(null);
      }
    }
  }, [pendingUploadFile, showToast]);

  const handleDuplicateCancel = useCallback(() => {
    setDuplicateBook(null);
    setPendingUploadFile(null);
  }, []);

  const handleDeleteRequest = useCallback((book: Book) => {
    setDeleteTarget(book);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      await deleteBook(deleteTarget.id);
      setBooks((prev) => prev.filter((b) => b.id !== deleteTarget.id));
      showToast(`"${deleteTarget.title}" deleted`);
    } catch {
      showToast('Failed to delete book');
    } finally {
      setDeleteTarget(null);
    }
  }, [deleteTarget, showToast]);

  const handleDeleteCancel = useCallback(() => {
    setDeleteTarget(null);
  }, []);

  const handleEmptyUploadClick = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.pdf,application/pdf';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) handleUpload(file);
    };
    input.click();
  }, [handleUpload]);

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-stone-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 flex items-center justify-center rounded-lg bg-amber-100">
              <i className="ri-book-open-line text-amber-600 text-sm"></i>
            </div>
            <h1 className="text-lg font-semibold text-stone-700">LuminaReader</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-400">{books.length} {books.length === 1 ? 'book' : 'books'}</span>
            <button
              onClick={() => navigate('/settings', { state: { from: '/' } })}
              className="w-8 h-8 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-100 cursor-pointer transition-colors"
              title="Settings"
            >
              <i className="ri-settings-3-line text-sm"></i>
            </button>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 max-w-7xl mx-auto w-full px-6 py-6">
        {/* Upload area */}
        <div className="mb-6">
          <UploadArea
            isUploading={isUploading}
            uploadProgress={uploadProgress}
            onFileSelect={handleUpload}
            onUploadCancel={handleUploadCancel}
          />
        </div>

        {/* Upload error */}
        {uploadError && !isUploading && (
          <div className="mb-4 flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            <i className="ri-error-warning-line text-red-400 text-sm"></i>
            <span className="text-sm text-red-600 flex-1">{uploadError}</span>
            <button
              onClick={handleRetryUpload}
              className="whitespace-nowrap text-xs font-medium text-red-500 hover:text-red-700 hover:underline cursor-pointer"
            >
              Retry
            </button>
            <button
              onClick={() => setUploadError(null)}
              className="w-6 h-6 flex items-center justify-center rounded text-stone-400 hover:text-stone-600 cursor-pointer"
            >
              <i className="ri-close-line text-sm"></i>
            </button>
          </div>
        )}

        {/* Sort bar */}
        {books.length > 0 && (
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-stone-500">My Bookshelf</h2>
            <SortSelector value={sortBy} onChange={setSortBy} />
          </div>
        )}

        {/* Loading state */}
        {loading && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="animate-pulse">
                <div className="aspect-[3/4] bg-stone-200 rounded-lg"></div>
                <div className="mt-2.5 h-4 bg-stone-200 rounded w-3/4"></div>
                <div className="mt-1.5 h-3 bg-stone-200 rounded w-1/2"></div>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && books.length === 0 && (
          <EmptyState onUploadClick={handleEmptyUploadClick} />
        )}

        {/* Book grid */}
        {!loading && books.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
            {sortedBooks.map((book) => (
              <BookCard
                key={book.id}
                book={book}
                onOpen={handleOpenBook}
                onDelete={handleDeleteRequest}
              />
            ))}
          </div>
        )}
      </div>

      {/* Duplicate reminder */}
      {duplicateBook && (
        <DuplicateReminder
          existingBook={duplicateBook}
          onOpenExisting={handleDuplicateOpenExisting}
          onCreateNew={handleDuplicateCreateNew}
          onCancel={handleDuplicateCancel}
        />
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <DeleteConfirmDialog
          book={deleteTarget}
          onConfirm={handleDeleteConfirm}
          onCancel={handleDeleteCancel}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
          <div className="bg-stone-800 text-white text-sm px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-2 animate-[fadeInUp_0.2s_ease-out]">
            <i className="ri-check-line text-amber-400 text-sm"></i>
            {toast}
          </div>
        </div>
      )}
    </div>
  );
}
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchLibrary,
  uploadPdf,
  deletePdf,
  PdfConflictError,
  TranslateApiError,
  type LibraryItem,
  type LibrarySort,
  type UploadProgress,
  type ConflictExisting,
} from '@/services/api';
import BookCard from './components/BookCard';
import UploadArea from './components/UploadArea';
import EmptyState from './components/EmptyState';
import SortSelector from './components/SortSelector';
import DeleteConfirmDialog from './components/DeleteConfirmDialog';
import DuplicateReminder from './components/DuplicateReminder';

function formatError(err: unknown, fallback: string): string {
  if (err instanceof TranslateApiError) return `[${err.code}] ${err.message}`;
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function BookshelfPage() {
  const navigate = useNavigate();
  const [books, setBooks] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<LibrarySort>('last_opened_at_desc');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [duplicateBook, setDuplicateBook] = useState<ConflictExisting | null>(null);
  const [pendingUploadFile, setPendingUploadFile] = useState<File | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<LibraryItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const abortRef = useRef(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadBooks = useCallback(async (sort: LibrarySort) => {
    setLoading(true);
    try {
      const data = await fetchLibrary(sort);
      setBooks(data);
    } catch {
      setBooks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBooks(sortBy);
  }, [loadBooks, sortBy]);

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const handleOpenBook = useCallback(
    (book: LibraryItem) => {
      navigate(`/reader/${book.pdf_id}`);
    },
    [navigate],
  );

  const runUpload = useCallback(
    async (file: File, forceCreateNew: boolean) => {
      abortRef.current = false;
      setUploadError(null);
      setIsUploading(true);
      setUploadProgress({ loaded: 0, total: file.size, percentage: 0 });

      try {
        const created = await uploadPdf(file, {
          forceCreateNew,
          onProgress: (progress) => {
            if (!abortRef.current) setUploadProgress(progress);
          },
        });
        if (abortRef.current) return;

        setIsUploading(false);
        setUploadProgress(null);
        showToast(`《${created.name}》已加入书架`);
        loadBooks(sortBy);
        setTimeout(() => {
          navigate(`/reader/${created.pdf_id}`);
        }, 400);
      } catch (err) {
        if (abortRef.current) return;
        setIsUploading(false);
        setUploadProgress(null);
        if (err instanceof PdfConflictError) {
          setDuplicateBook(err.existing);
          setPendingUploadFile(file);
          return;
        }
        setUploadError(formatError(err, '上传失败，请重试'));
      }
    },
    [sortBy, showToast, loadBooks, navigate],
  );

  const handleUpload = useCallback(
    (file: File) => {
      if (isUploading) return;
      setDuplicateBook(null);
      setPendingUploadFile(null);
      runUpload(file, false);
    },
    [isUploading, runUpload],
  );

  const handleUploadCancel = useCallback(() => {
    abortRef.current = true;
    setIsUploading(false);
    setUploadProgress(null);
  }, []);

  const handleRetryUpload = useCallback(() => {
    if (pendingUploadFile) handleUpload(pendingUploadFile);
  }, [pendingUploadFile, handleUpload]);

  const handleDuplicateOpenExisting = useCallback(() => {
    if (duplicateBook) navigate(`/reader/${duplicateBook.pdf_id}`);
    setDuplicateBook(null);
    setPendingUploadFile(null);
  }, [duplicateBook, navigate]);

  const handleDuplicateCreateNew = useCallback(() => {
    const file = pendingUploadFile;
    setDuplicateBook(null);
    setPendingUploadFile(null);
    if (file) runUpload(file, true);
  }, [pendingUploadFile, runUpload]);

  const handleDuplicateCancel = useCallback(() => {
    setDuplicateBook(null);
    setPendingUploadFile(null);
  }, []);

  const handleDeleteRequest = useCallback((book: LibraryItem) => {
    setDeleteTarget(book);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      await deletePdf(deleteTarget.pdf_id);
      setBooks((prev) => prev.filter((b) => b.pdf_id !== deleteTarget.pdf_id));
      showToast(`《${deleteTarget.name}》已删除`);
    } catch {
      showToast('删除失败');
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
      <div className="bg-white border-b border-stone-200">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 flex items-center justify-center rounded-lg bg-amber-100">
              <i className="ri-book-open-line text-amber-600 text-sm"></i>
            </div>
            <h1 className="text-lg font-semibold text-stone-700">LuminaReader</h1>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-stone-400">{books.length} 本书</span>
          </div>
        </div>
      </div>

      <div className="flex-1 max-w-7xl mx-auto w-full px-6 py-6">
        <div className="mb-6">
          <UploadArea
            isUploading={isUploading}
            uploadProgress={uploadProgress}
            onFileSelect={handleUpload}
            onUploadCancel={handleUploadCancel}
          />
        </div>

        {uploadError && !isUploading && (
          <div className="mb-4 flex items-center gap-3 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            <i className="ri-error-warning-line text-red-400 text-sm"></i>
            <span className="text-sm text-red-600 flex-1">{uploadError}</span>
            {pendingUploadFile && (
              <button
                onClick={handleRetryUpload}
                className="whitespace-nowrap text-xs font-medium text-red-500 hover:text-red-700 hover:underline cursor-pointer"
              >
                重试
              </button>
            )}
            <button
              onClick={() => setUploadError(null)}
              className="w-6 h-6 flex items-center justify-center rounded text-stone-400 hover:text-stone-600 cursor-pointer"
            >
              <i className="ri-close-line text-sm"></i>
            </button>
          </div>
        )}

        {books.length > 0 && (
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium text-stone-500">我的书架</h2>
            <SortSelector value={sortBy} onChange={setSortBy} />
          </div>
        )}

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

        {!loading && books.length === 0 && (
          <EmptyState onUploadClick={handleEmptyUploadClick} />
        )}

        {!loading && books.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
            {books.map((book) => (
              <BookCard
                key={book.pdf_id}
                book={book}
                onOpen={handleOpenBook}
                onDelete={handleDeleteRequest}
              />
            ))}
          </div>
        )}
      </div>

      {duplicateBook && (
        <DuplicateReminder
          existingBook={duplicateBook}
          onOpenExisting={handleDuplicateOpenExisting}
          onCreateNew={handleDuplicateCreateNew}
          onCancel={handleDuplicateCancel}
        />
      )}

      {deleteTarget && (
        <DeleteConfirmDialog
          book={deleteTarget}
          onConfirm={handleDeleteConfirm}
          onCancel={handleDeleteCancel}
        />
      )}

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

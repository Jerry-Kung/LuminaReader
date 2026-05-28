interface ToolbarProps {
  fileName: string;
  numPages: number;
  currentPage: number;
  scale: number;
  hasSelection: boolean;
  isTranslating: boolean;
  onOpenFile: () => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onGoToPage: (page: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onTranslate: () => void;
}

export default function Toolbar({
  fileName,
  numPages,
  currentPage,
  scale,
  hasSelection,
  isTranslating,
  onOpenFile,
  onPrevPage,
  onNextPage,
  onGoToPage,
  onZoomIn,
  onZoomOut,
  onTranslate,
}: ToolbarProps) {
  const handlePageInput = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const val = parseInt((e.target as HTMLInputElement).value, 10);
      if (!isNaN(val)) {
        onGoToPage(val);
      }
    }
  };

  return (
    <div className="flex items-center justify-between px-5 py-3 bg-white border-b border-stone-200">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenFile}
          className="whitespace-nowrap flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-700 bg-stone-100 rounded-md hover:bg-stone-200 transition-colors cursor-pointer"
        >
          <i className="ri-folder-open-line"></i>
          Open PDF
        </button>
        {fileName && (
          <span className="text-sm text-stone-500 truncate max-w-[200px]" title={fileName}>
            {fileName}
          </span>
        )}
      </div>

      {numPages > 0 && (
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1">
            <button
              onClick={onPrevPage}
              disabled={currentPage <= 1}
              className="w-8 h-8 flex items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <i className="ri-arrow-left-s-line"></i>
            </button>
            <div className="flex items-center gap-1 text-sm">
              <input
                type="text"
                defaultValue={currentPage}
                key={currentPage}
                onKeyDown={handlePageInput}
                className="w-10 h-8 text-center text-sm border border-stone-200 rounded-md bg-white focus:outline-none focus:border-amber-400"
              />
              <span className="text-stone-400">/ {numPages}</span>
            </div>
            <button
              onClick={onNextPage}
              disabled={currentPage >= numPages}
              className="w-8 h-8 flex items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <i className="ri-arrow-right-s-line"></i>
            </button>
          </div>

          <div className="w-px h-5 bg-stone-200" />

          <div className="flex items-center gap-1">
            <button
              onClick={onZoomOut}
              disabled={scale <= 0.4}
              className="w-8 h-8 flex items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <i className="ri-zoom-out-line"></i>
            </button>
            <span className="text-sm text-stone-500 w-14 text-center">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={onZoomIn}
              disabled={scale >= 3.0}
              className="w-8 h-8 flex items-center justify-center rounded-md text-stone-600 hover:bg-stone-100 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
            >
              <i className="ri-zoom-in-line"></i>
            </button>
          </div>

          <div className="w-px h-5 bg-stone-200" />

          <button
            onClick={onTranslate}
            disabled={!hasSelection || isTranslating}
            className="whitespace-nowrap flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
          >
            {isTranslating ? (
              <>
                <i className="ri-loader-4-line animate-spin"></i>
                Translating...
              </>
            ) : (
              <>
                <i className="ri-translate-2"></i>
                Translate
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
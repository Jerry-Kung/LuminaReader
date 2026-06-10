export type CursorMode = 'off' | 'text' | 'screenshot';

interface ToolbarProps {
  fileName: string;
  numPages: number;
  currentPage: number;
  scale: number;
  cursorMode: CursorMode;
  /** 扫描版 PDF 检测到的页集合 size。>0 时 text 模式按钮 disabled 并提示 Toast。 */
  scanPageCount: number;
  onOpenFile: () => void;
  onPrevPage: () => void;
  onNextPage: () => void;
  onGoToPage: (page: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onSelectCursorMode: (mode: CursorMode) => void;
  onTextModeBlockedByScan?: () => void;
  onOpenSettings: () => void;
}

export default function Toolbar({
  fileName,
  numPages,
  currentPage,
  scale,
  cursorMode,
  scanPageCount,
  onOpenFile,
  onPrevPage,
  onNextPage,
  onGoToPage,
  onZoomIn,
  onZoomOut,
  onSelectCursorMode,
  onTextModeBlockedByScan,
  onOpenSettings,
}: ToolbarProps) {
  const handlePageInput = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const val = parseInt((e.target as HTMLInputElement).value, 10);
      if (!isNaN(val)) {
        onGoToPage(val);
      }
    }
  };

  const isScanBook = scanPageCount > 0;
  const isText = cursorMode === 'text';
  const isShot = cursorMode === 'screenshot';

  const handleTextClick = () => {
    if (isScanBook) {
      onTextModeBlockedByScan?.();
      return;
    }
    onSelectCursorMode(isText ? 'off' : 'text');
  };

  const handleShotClick = () => {
    onSelectCursorMode(isShot ? 'off' : 'screenshot');
  };

  return (
    <div className="flex items-center justify-between px-5 py-3 bg-white border-b border-stone-200">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenSettings}
          className="w-8 h-8 flex items-center justify-center rounded-md text-stone-400 hover:bg-stone-100 hover:text-stone-700 transition-colors cursor-pointer"
          title="设置"
        >
          <i className="ri-settings-3-line"></i>
        </button>
        <button
          onClick={onOpenFile}
          className="whitespace-nowrap flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-700 bg-stone-100 rounded-md hover:bg-stone-200 transition-colors cursor-pointer"
        >
          <i className="ri-folder-open-line"></i>
          Open PDF
        </button>
        {numPages > 0 && (
          <div className="flex items-center gap-1 border border-stone-200 rounded-md p-0.5 bg-stone-50">
            <button
              onClick={handleTextClick}
              disabled={isScanBook}
              className={`whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium rounded transition-colors ${
                isText
                  ? 'bg-amber-100 text-amber-700'
                  : isScanBook
                    ? 'text-stone-300 cursor-not-allowed'
                    : 'text-stone-600 hover:bg-stone-100 cursor-pointer'
              }`}
              title={
                isScanBook
                  ? '本书为扫描版，无法选择文字'
                  : isText
                    ? '退出文字选择（Esc）'
                    : '选择文字'
              }
            >
              <i className="ri-text"></i>
              文字
            </button>
            <button
              onClick={handleShotClick}
              className={`whitespace-nowrap flex items-center gap-1.5 px-2.5 py-1.5 text-sm font-medium rounded transition-colors cursor-pointer ${
                isShot
                  ? 'bg-amber-100 text-amber-700'
                  : 'text-stone-600 hover:bg-stone-100'
              }`}
              title={isShot ? '退出截图选择（Esc）' : '截图选择'}
            >
              <i className="ri-crop-line"></i>
              截图
            </button>
          </div>
        )}
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
        </div>
      )}
    </div>
  );
}

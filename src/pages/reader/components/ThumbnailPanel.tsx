import { useState, useRef, useEffect, useCallback } from 'react';
import type * as pdfjsLib from 'pdfjs-dist';

interface ThumbnailPanelProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  numPages: number;
  currentPage: number;
  onPageClick: (page: number) => void;
  isLoading: boolean;
}

interface PageDim {
  width: number;
  height: number;
}

export default function ThumbnailPanel({
  pdfDoc,
  numPages,
  currentPage,
  onPageClick,
  isLoading,
}: ThumbnailPanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [pageDimensions, setPageDimensions] = useState<Record<number, PageDim>>();
  const [thumbnailUrls, setThumbnailUrls] = useState<Record<number, string>>();
  const [renderingPages, setRenderingPages] = useState<Set<number>>(new Set());
  const [errorPages, setErrorPages] = useState<Set<number>>(new Set());
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Record<number, HTMLDivElement | null>>();
  const observerRef = useRef<IntersectionObserver | null>(null);
  const renderedPagesRef = useRef<Set<number>>(new Set());

  // Reset all thumbnail state when PDF changes
  useEffect(() => {
    setPageDimensions({});
    setThumbnailUrls({});
    setRenderingPages(new Set());
    setErrorPages(new Set());
    setLoadedPages(new Set());
    renderedPagesRef.current = new Set();
    itemRefs.current = {};
  }, [pdfDoc, numPages]);

  // Load page dimensions for aspect ratio calculation
  useEffect(() => {
    if (!pdfDoc || numPages === 0) return;
    const loadDimensions = async () => {
      const dims: Record<number, PageDim> = {};
      await Promise.all(
        Array.from({ length: numPages }, (_, i) => i + 1).map(async (pageNum) => {
          try {
            const page = await pdfDoc.getPage(pageNum);
            const viewport = page.getViewport({ scale: 1 });
            dims[pageNum] = { width: viewport.width, height: viewport.height };
          } catch {
            dims[pageNum] = { width: 595, height: 842 };
          }
        }),
      );
      setPageDimensions(dims);
    };
    loadDimensions();
  }, [pdfDoc, numPages]);

  // Render a single thumbnail page
  const renderThumbnail = useCallback(
    async (pageNum: number) => {
      if (!pdfDoc || renderedPagesRef.current.has(pageNum) || errorPages.has(pageNum)) return;

      renderedPagesRef.current.add(pageNum);
      setRenderingPages((prev) => new Set(prev).add(pageNum));

      try {
        const page = await pdfDoc.getPage(pageNum);
        const viewport = page.getViewport({ scale: 0.25 });
        const canvas = document.createElement('canvas');
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        const ctx = canvas.getContext('2d')!;
        await page.render({ canvasContext: ctx, viewport }).promise;
        const dataUrl = canvas.toDataURL('image/png');

        setThumbnailUrls((prev) => ({ ...prev, [pageNum]: dataUrl }));
      } catch {
        setErrorPages((prev) => new Set(prev).add(pageNum));
      } finally {
        setRenderingPages((prev) => {
          const next = new Set(prev);
          next.delete(pageNum);
          return next;
        });
      }
    },
    [pdfDoc, errorPages],
  );

  // IntersectionObserver for lazy rendering
  useEffect(() => {
    if (!scrollRef.current || isCollapsed || numPages === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const pageNum = parseInt(entry.target.getAttribute('data-page') || '0', 10);
          if (entry.isIntersecting && pageNum > 0) {
            renderThumbnail(pageNum);
          }
        });
      },
      { root: scrollRef.current, rootMargin: '100px', threshold: 0 },
    );

    observerRef.current = observer;

    // Observe all items currently in refs
    Object.values(itemRefs.current).forEach((el) => {
      if (el) observer.observe(el);
    });

    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [numPages, isCollapsed, renderThumbnail]);

  // Ref callback for each thumbnail item
  const setItemRef = useCallback(
    (pageNum: number) => (el: HTMLDivElement | null) => {
      if (el) {
        itemRefs.current[pageNum] = el;
        if (observerRef.current) {
          observerRef.current.observe(el);
        }
      } else {
        delete itemRefs.current[pageNum];
      }
    },
    [],
  );

  // Auto-scroll current page into view
  useEffect(() => {
    const el = itemRefs.current[currentPage];
    if (el && scrollRef.current && !isCollapsed) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [currentPage, isCollapsed]);

  // Get aspect ratio for a page
  const getAspectRatio = useCallback(
    (pageNum: number) => {
      const dim = pageDimensions[pageNum];
      if (!dim) return 3 / 4;
      return dim.height / dim.width;
    },
    [pageDimensions],
  );

  const handleToggleCollapse = () => {
    setIsCollapsed((prev) => !prev);
  };

  const hasContent = pdfDoc && numPages > 0;

  return (
    <div
      className={`flex-shrink-0 flex flex-col border-r border-stone-200 bg-[#f7f4f0] transition-all duration-200 ease-out overflow-hidden ${isCollapsed ? 'w-8' : 'w-[180px]'}`}
    >
      {/* Top bar */}
      <div className="flex-shrink-0 h-9 flex items-center border-b border-stone-200/60">
        {!isCollapsed && (
          <div className="flex items-center justify-between w-full px-2.5">
            <span className="text-[11px] font-medium text-stone-400 tracking-wide">页面</span>
            <button
              onClick={handleToggleCollapse}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-stone-200/50 text-stone-400 hover:text-stone-600 transition-colors cursor-pointer"
              title="收起"
            >
              <i className="ri-arrow-left-s-line text-sm"></i>
            </button>
          </div>
        )}
        {isCollapsed && (
          <div className="w-full flex justify-center pt-1.5">
            <button
              onClick={handleToggleCollapse}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-stone-200/50 text-stone-400 hover:text-stone-600 transition-colors cursor-pointer"
              title="展开"
            >
              <i className="ri-arrow-right-s-line text-sm"></i>
            </button>
          </div>
        )}
      </div>

      {/* Thumbnails */}
      {!isCollapsed && (
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto scrollbar-thin py-3 px-2.5"
        >
          {isLoading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="w-full rounded-md overflow-hidden">
                  <div className="w-full aspect-[3/4] skeleton-diagonal" />
                  <div className="mt-1.5 h-3 w-8 rounded bg-stone-200" />
                </div>
              ))}
            </div>
          )}

          {!isLoading && !hasContent && (
            <div className="flex flex-col items-center justify-center h-40 gap-2 text-stone-400">
              <i className="ri-file-pdf-2-line text-lg"></i>
              <span className="text-[10px]">未打开 PDF</span>
            </div>
          )}

          {!isLoading && hasContent && (
            <div className="space-y-2.5">
              {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
                const isCurrent = pageNum === currentPage;
                const isRendering = renderingPages.has(pageNum);
                const hasError = errorPages.has(pageNum);
                const hasThumbnail = !!thumbnailUrls[pageNum];
                const aspectRatio = getAspectRatio(pageNum);
                const isLoaded = loadedPages.has(pageNum);

                return (
                  <div
                    key={pageNum}
                    ref={setItemRef(pageNum)}
                    data-page={pageNum}
                    onClick={() => onPageClick(pageNum)}
                    className={`group cursor-pointer rounded-md border transition-all duration-150 ${isCurrent ? 'bg-[#fef9f3] border-l-2 border-amber-400 border-stone-200/60 hover:bg-[#fdf6ed]' : 'bg-white border-stone-200/60 hover:border-stone-300/80 hover:bg-stone-50/50'}`}
                  >
                    {/* Thumbnail image area */}
                    <div className="px-2 pt-2">
                      <div
                        className="relative w-full rounded overflow-hidden bg-white"
                        style={{ paddingBottom: `${aspectRatio * 100}%` }}
                      >
                        {/* Skeleton placeholder */}
                        {isRendering && !hasThumbnail && (
                          <div className="absolute inset-0 skeleton-diagonal" />
                        )}

                        {/* Error state */}
                        {hasError && (
                          <div className="absolute inset-0 flex items-center justify-center bg-stone-100">
                            <i className="ri-error-warning-line text-stone-400 text-sm"></i>
                          </div>
                        )}

                        {/* Rendered thumbnail */}
                        {hasThumbnail && (
                          <img
                            src={thumbnailUrls[pageNum]}
                            alt={`第 ${pageNum} 页`}
                            className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-150 ${isLoaded ? 'opacity-100' : 'opacity-0'}`}
                            onLoad={() =>
                              setLoadedPages((prev) => new Set(prev).add(pageNum))
                            }
                          />
                        )}

                        {/* Waiting placeholder (not yet intersecting) */}
                        {!isRendering && !hasThumbnail && !hasError && (
                          <div className="absolute inset-0 skeleton-diagonal" />
                        )}
                      </div>
                    </div>

                    {/* Page number */}
                    <div className="px-2 py-1.5">
                      <span
                        className={`text-[10px] ${isCurrent ? 'text-amber-600 font-medium' : 'text-stone-400'}`}
                      >
                        {pageNum}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
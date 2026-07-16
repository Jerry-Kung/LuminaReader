/**
 * V1.0.4 F1 左侧页面缩略图列表内容（V1.2.2 起外壳由 SidebarPanel 接管）。
 *
 * 视觉来自 readdy.ai 交付（米色背景 / 当前页琥珀左竖条 + 米色块 /
 * skeleton-diagonal 占位 / scrollbar-thin），与 PDF 主视图、AI 助手共用低饱和米色系。
 * 渲染走 usePdfThumbnails（LRU 50 + 串行队列），避免厚书并发 OOM。
 *
 * 折叠/Tab 切换由 SidebarPanel 受控，通过 `active` 暂停 observer 与滚动跟随。
 */
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type * as pdfjsLib from 'pdfjs-dist';
import { usePdfThumbnails } from '@/hooks/usePdfThumbnails';

interface ThumbnailListProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  numPages: number;
  currentPage: number;
  onPageClick: (page: number) => void;
  isLoading: boolean;
  /** 所在 Tab 是否可见：不可见时暂停 observer 与滚动跟随（原 collapsed 语义） */
  active: boolean;
}

interface PageDim {
  width: number;
  height: number;
}

export default function ThumbnailList({
  pdfDoc,
  numPages,
  currentPage,
  onPageClick,
  isLoading,
  active,
}: ThumbnailListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const observerRef = useRef<IntersectionObserver | null>(null);
  const didInitialScrollRef = useRef(false);
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set());
  const [pageDims, setPageDims] = useState<Map<number, PageDim>>(new Map());

  const { getThumbnail } = usePdfThumbnails(pdfDoc);

  // 切书 → 清理可见集合 & 尺寸缓存 + 重置首次滚动标记。
  // 注意：不能在这里清 itemRefs.current —— ref callback 已经在 commit 阶段把
  // 新 item 的 DOM 写进去了，这里再 clear 会把刚注册的引用全部抹掉，
  // 导致紧随其后的 observer 和 scroll effect 拿到空 Map。
  // item 自身卸载时 ref(null) 会自然清掉自己，无需手动干预。
  useEffect(() => {
    setVisiblePages(new Set());
    setPageDims(new Map());
    didInitialScrollRef.current = false;
  }, [pdfDoc, numPages]);

  // 预读所有页面尺寸（仅 getPage(...).getViewport，不渲染 canvas，开销低）
  useEffect(() => {
    if (!pdfDoc || numPages === 0) return;
    let cancelled = false;
    (async () => {
      const dims = new Map<number, PageDim>();
      for (let i = 1; i <= numPages; i++) {
        try {
          const page = await pdfDoc.getPage(i);
          const vp = page.getViewport({ scale: 1 });
          dims.set(i, { width: vp.width, height: vp.height });
        } catch {
          dims.set(i, { width: 595, height: 842 }); // A4 兜底
        }
        if (cancelled) return;
      }
      if (!cancelled) setPageDims(dims);
    })();
    return () => {
      cancelled = true;
    };
  }, [pdfDoc, numPages]);

  // IntersectionObserver：仅可见（含 100px 缓冲）页面入 visiblePages
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !active || numPages === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        setVisiblePages((prev) => {
          const next = new Set(prev);
          let changed = false;
          entries.forEach((e) => {
            const pageNum = Number(e.target.getAttribute('data-page') || '0');
            if (e.isIntersecting && pageNum > 0 && !next.has(pageNum)) {
              next.add(pageNum);
              changed = true;
            }
          });
          return changed ? next : prev;
        });
      },
      { root, rootMargin: '100px', threshold: 0 },
    );
    observerRef.current = observer;
    itemRefs.current.forEach((el) => observer.observe(el));
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [numPages, active]);

  const setItemRef = useCallback(
    (pageNum: number) => (el: HTMLDivElement | null) => {
      if (el) {
        itemRefs.current.set(pageNum, el);
        if (observerRef.current) observerRef.current.observe(el);
      } else {
        itemRefs.current.delete(pageNum);
      }
    },
    [],
  );

  // 翻页 → 当前页滚到可见区
  // 首次（含重进书时已恢复到 last_read_page、或 pdfDoc/列表刚就绪）以 auto+center 瞬时居中，
  // 避免从第 1 页平滑滚到第 N 页的长动画；后续翻页用 smooth+nearest 做小幅调整。
  // V1.1.3 F3：连续滚动模式下 currentPage 会随主视图滚动持续变化；scrollIntoView 加 200ms throttle
  // 避免动画堆积。throttle 窗口内最后一次目标会在窗口结束时落地一次。
  const lastScrollAtRef = useRef<number>(0);
  const pendingPageRef = useRef<number | null>(null);
  const trailingTimerRef = useRef<number | null>(null);
  const THROTTLE_MS = 200;

  const scrollToPage = useCallback((pageNum: number, initial: boolean) => {
    const el = itemRefs.current.get(pageNum);
    if (!el) return;
    if (initial) {
      el.scrollIntoView({ behavior: 'auto', block: 'center' });
    } else {
      // 节流窗口内的中间翻阅切到瞬时滚动，避免 smooth 动画堆积
      el.scrollIntoView({ behavior: 'auto', block: 'nearest' });
    }
  }, []);

  useEffect(() => {
    if (!active || numPages === 0) return;
    if (!didInitialScrollRef.current) {
      const el = itemRefs.current.get(currentPage);
      if (!el) return;
      scrollToPage(currentPage, true);
      didInitialScrollRef.current = true;
      lastScrollAtRef.current = performance.now();
      return;
    }
    const now = performance.now();
    const elapsed = now - lastScrollAtRef.current;
    if (elapsed >= THROTTLE_MS) {
      scrollToPage(currentPage, false);
      lastScrollAtRef.current = now;
      pendingPageRef.current = null;
      if (trailingTimerRef.current !== null) {
        window.clearTimeout(trailingTimerRef.current);
        trailingTimerRef.current = null;
      }
    } else {
      pendingPageRef.current = currentPage;
      if (trailingTimerRef.current === null) {
        trailingTimerRef.current = window.setTimeout(() => {
          trailingTimerRef.current = null;
          const target = pendingPageRef.current;
          pendingPageRef.current = null;
          if (target !== null) {
            scrollToPage(target, false);
            lastScrollAtRef.current = performance.now();
          }
        }, THROTTLE_MS - elapsed);
      }
    }
  }, [currentPage, active, numPages, pdfDoc, isLoading, scrollToPage]);

  useEffect(() => {
    return () => {
      if (trailingTimerRef.current !== null) {
        window.clearTimeout(trailingTimerRef.current);
        trailingTimerRef.current = null;
      }
    };
  }, []);

  const aspectRatioFor = useCallback(
    (pageNum: number) => {
      const dim = pageDims.get(pageNum);
      if (!dim) return 4 / 3; // 默认 height/width
      return dim.height / dim.width;
    },
    [pageDims],
  );

  const pages = useMemo(
    () => Array.from({ length: numPages }, (_, i) => i + 1),
    [numPages],
  );

  const hasContent = pdfDoc && numPages > 0;

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin py-3 px-2.5">
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
          {pages.map((pageNum) => (
            <ThumbnailItem
              key={pageNum}
              ref={setItemRef(pageNum)}
              pageNum={pageNum}
              isCurrent={pageNum === currentPage}
              visible={visiblePages.has(pageNum)}
              aspectRatio={aspectRatioFor(pageNum)}
              onClick={() => onPageClick(pageNum)}
              getThumbnail={getThumbnail}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface ThumbnailItemProps {
  pageNum: number;
  isCurrent: boolean;
  visible: boolean;
  aspectRatio: number;
  onClick: () => void;
  getThumbnail: (page: number) => Promise<string>;
}

const ThumbnailItem = forwardRef<HTMLDivElement, ThumbnailItemProps>(
  function ThumbnailItem(
    { pageNum, isCurrent, visible, aspectRatio, onClick, getThumbnail },
    ref,
  ) {
    const [url, setUrl] = useState<string | null>(null);
    const [errored, setErrored] = useState(false);
    const [imgLoaded, setImgLoaded] = useState(false);

    useEffect(() => {
      if (!visible || url || errored) return;
      let cancelled = false;
      getThumbnail(pageNum)
        .then((u) => {
          if (!cancelled) setUrl(u);
        })
        .catch(() => {
          if (!cancelled) setErrored(true);
        });
      return () => {
        cancelled = true;
      };
    }, [visible, url, errored, getThumbnail, pageNum]);

    return (
      <div
        ref={ref}
        data-page={pageNum}
        onClick={onClick}
        className={`group cursor-pointer rounded-md border transition-all duration-150 ${
          isCurrent
            ? 'bg-[#fef9f3] border-l-2 border-amber-400 border-stone-200/60 hover:bg-[#fdf6ed]'
            : 'bg-white border-stone-200/60 hover:border-stone-300/80 hover:bg-stone-50/50'
        }`}
      >
        <div className="px-2 pt-2">
          <div
            className="relative w-full rounded overflow-hidden bg-white"
            style={{ paddingBottom: `${aspectRatio * 100}%` }}
          >
            {url ? (
              <img
                src={url}
                alt={`第 ${pageNum} 页`}
                className={`absolute inset-0 w-full h-full object-contain transition-opacity duration-150 ${
                  imgLoaded ? 'opacity-100' : 'opacity-0'
                }`}
                onLoad={() => setImgLoaded(true)}
              />
            ) : errored ? (
              <div className="absolute inset-0 flex items-center justify-center bg-stone-100">
                <i className="ri-error-warning-line text-stone-400 text-sm"></i>
              </div>
            ) : (
              <div className="absolute inset-0 skeleton-diagonal" />
            )}
          </div>
        </div>
        <div className="px-2 py-1.5">
          <span
            className={`text-[10px] ${
              isCurrent ? 'text-amber-600 font-medium' : 'text-stone-400'
            }`}
          >
            {pageNum}
          </span>
        </div>
      </div>
    );
  },
);

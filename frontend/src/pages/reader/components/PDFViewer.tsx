import { useRef, useEffect, useState, useCallback, useMemo, memo } from 'react';
import * as pdfjsLib from 'pdfjs-dist';

/**
 * V1.1.3 F1 / F4 / F6 / F7 / F8 多页连续滚动 PDFViewer。
 *
 * 渲染模型：
 *  - 容器为单一 scroll 区，子元素是 numPages 个绝对定位的 PageSlot
 *  - 每个 PageSlot 占据 (width × height) 的版位，无论是否实际渲染 canvas（保留 scroll 长度）
 *  - 仅"可见区上下各扩 1 个 viewport + ±1 页 buffer"的页面会真正实例化 canvas（IntersectionObserver 等价的中心点反推）
 *  - 滚动时 rAF 节流：viewport 中心点反推 currentPage + 计算 offset (= (centerY - pageTop) / pageHeight)
 *
 * 阅读位置（与 usePdfReadingPosition 协作）：
 *  - 写：onPositionChange(page, offset) → 上报到 usePDF.reportPosition
 *  - 读：pendingScrollTarget=(page, offset) → 让 (page, offset) 落在 viewport 中心（与反推算法对称）
 *
 * R-V104-F2 删除：原"放大平移模式滚到边界二次确认翻页"逻辑（boundaryHitRef / handleWheel 边界判定）全部去除；
 * 连续滚动模式下边界由浏览器原生 scrollHeight/scrollTop 处理。
 *
 * 框选截图（V1.1.3 D-V113-6 起点页 clamp）：
 *  - mousedown 时记录起点页 selectionStartPage
 *  - 拖动到另一页时坐标 clamp 回起点页边界
 *  - selectedArea 携带 page 字段，captureImage 据此截目标页
 *
 * 键盘：
 *  - Esc：退出选择模式 / 清除已确认选区（V1.0.x 既有）
 *  - PageDown / PageUp：滚一屏（viewport 高度 × 0.95，含小幅上下文重叠）；焦点在 INPUT/TEXTAREA 时短路
 *
 * V1.1.4 预留：每个 PageSlot 内含 .textLayer 占位 div，V1.1.4 启动期填入 PDF.js renderTextLayer。
 */

interface PDFViewerProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  numPages: number;
  scale: number;
  isLoading: boolean;
  error: string | null;
  onSelectionChange: (selection: SelectedArea | null) => void;
  selectedArea: SelectedArea | null;
  onZoomIn: () => void;
  onZoomOut: () => void;
  isSelecting: boolean;
  onSelectionModeExit: () => void;
  pendingScrollTarget: { page: number; offset: number } | null;
  onScrollTargetConsumed: () => void;
  onPositionChange: (page: number, offset: number) => void;
  /**
   * V1.1.4 三态光标：
   *  - 'off'         默认手型，textLayer 不接收鼠标事件
   *  - 'text'        I-beam，textLayer pointer-events:auto，允许原生文本选区
   *  - 'screenshot'  crosshair（沿用 V1.1.3 框选），textLayer 不接收事件
   * 默认 'off'；不传时等价于 'off'。
   */
  cursorMode?: 'off' | 'text' | 'screenshot';
  /**
   * V1.1.4：扫描版 PDF 检测回调。
   * PDFPage textLayer 渲染完毕后，若 textContent.trim()==='' 则上报该 pageNum；
   * 父组件据此累积 set 判断是否拦截 cursorMode='text' 切换并提示 Toast。
   */
  onScanPageDetected?: (pageNum: number) => void;
  /**
   * 当父组件需要把 PDFViewer 滚动容器引用给到其他 hook（如 useTextSelection）时，
   * 通过此函数把内部 containerRef 暴露给上层。仅在 mount/unmount 时调用。
   */
  onContainerRefReady?: (el: HTMLDivElement | null) => void;
}

export interface SelectedArea {
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
}

interface PageBaseDim {
  baseWidth: number;
  baseHeight: number;
}

interface PageMeta {
  pageNum: number;
  width: number;
  height: number;
  top: number;
}

const PAGE_GAP = 16;
const SIDE_PADDING = 24;
const POSITION_REPORT_OFFSET_EPSILON = 0.005;

/**
 * V1.1.4 PoC 期改造为常态：textLayer 始终渲染；交互由 cursorMode prop 控制。
 *  - cursorMode='text' 时 textLayer pointer-events:auto，允许原生文本选区
 *  - 其余模式下 pointer-events:none，保持 V1.1.3 既有行为
 * 跨页 Selection 抓取由 useTextSelection hook 在父组件层完成（监听同一容器的 mouseup）。
 */

export default function PDFViewer({
  pdfDoc,
  numPages,
  scale,
  isLoading,
  error,
  onSelectionChange,
  selectedArea,
  onZoomIn,
  onZoomOut,
  isSelecting,
  onSelectionModeExit,
  pendingScrollTarget,
  onScrollTargetConsumed,
  onPositionChange,
  cursorMode = 'off',
  onScanPageDetected,
  onContainerRefReady,
}: PDFViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [pageDims, setPageDims] = useState<Map<number, PageBaseDim>>(new Map());
  const [visiblePages, setVisiblePages] = useState<Set<number>>(new Set([1]));
  const [drag, setDrag] = useState<{
    page: number;
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
  } | null>(null);

  // ---- 容器尺寸监听 ----
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setContainerWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---- 把 containerRef 暴露给父组件（用于 useTextSelection 在同一容器上挂 mouseup）----
  useEffect(() => {
    onContainerRefReady?.(containerRef.current);
    return () => {
      onContainerRefReady?.(null);
    };
  }, [onContainerRefReady]);

  // ---- 预读所有页 baseDim（pdfDoc 内部对 getPage 有缓存）----
  useEffect(() => {
    if (!pdfDoc || numPages === 0) {
      setPageDims(new Map());
      return;
    }
    let cancelled = false;
    (async () => {
      const dims = new Map<number, PageBaseDim>();
      for (let i = 1; i <= numPages; i++) {
        if (cancelled) return;
        try {
          const page = await pdfDoc.getPage(i);
          const vp = page.getViewport({ scale: 1 });
          dims.set(i, { baseWidth: vp.width, baseHeight: vp.height });
        } catch {
          dims.set(i, { baseWidth: 595, baseHeight: 842 });
        }
      }
      if (!cancelled) setPageDims(dims);
    })();
    return () => {
      cancelled = true;
    };
  }, [pdfDoc, numPages]);

  // ---- fitScale + pageMetas ----
  // fitScale 用第一页 baseWidth 作为基准（大部分书每页等宽；若不等宽，各页仍按自身 baseWidth × fitScale 计算实际宽度）
  const { pageMetas, totalHeight } = useMemo(() => {
    if (containerWidth === 0 || pageDims.size === 0 || numPages === 0) {
      return { pageMetas: [] as PageMeta[], totalHeight: 0 };
    }
    const first = pageDims.get(1);
    if (!first) return { pageMetas: [] as PageMeta[], totalHeight: 0 };
    const innerWidth = Math.max(1, containerWidth - SIDE_PADDING * 2);
    const fs = innerWidth / first.baseWidth;
    const metas: PageMeta[] = [];
    let top = PAGE_GAP;
    for (let i = 1; i <= numPages; i++) {
      const dim = pageDims.get(i);
      if (!dim) break;
      const w = dim.baseWidth * fs * scale;
      const h = dim.baseHeight * fs * scale;
      metas.push({ pageNum: i, width: w, height: h, top });
      top += h + PAGE_GAP;
    }
    return { pageMetas: metas, totalHeight: top };
  }, [containerWidth, pageDims, numPages, scale]);

  // ---- scroll 反推 ----
  const rafRef = useRef<number | null>(null);
  const lastReportedRef = useRef<{ page: number; offset: number } | null>(null);

  const computePosition = useCallback(() => {
    rafRef.current = null;
    const el = containerRef.current;
    if (!el || pageMetas.length === 0) return;
    const scrollTop = el.scrollTop;
    const vh = el.clientHeight;
    const centerY = scrollTop + vh / 2;

    // 二分找到 centerY 所在页（pageMetas 已按 top 升序）
    let current = pageMetas[0];
    for (const m of pageMetas) {
      if (centerY < m.top + m.height) {
        current = m;
        break;
      }
      current = m;
    }
    const offset = Math.max(
      0,
      Math.min(1, (centerY - current.top) / current.height),
    );
    const last = lastReportedRef.current;
    if (
      !last ||
      last.page !== current.pageNum ||
      Math.abs(last.offset - offset) > POSITION_REPORT_OFFSET_EPSILON
    ) {
      lastReportedRef.current = { page: current.pageNum, offset };
      onPositionChange(current.pageNum, offset);
    }

    // visiblePages：可见区上下各扩 1 个 vh + ±1 页 buffer
    const lo = scrollTop - vh;
    const hi = scrollTop + vh * 2;
    const base = new Set<number>();
    for (const m of pageMetas) {
      if (m.top + m.height >= lo && m.top <= hi) base.add(m.pageNum);
    }
    const expanded = new Set<number>(base);
    base.forEach((p) => {
      if (p > 1) expanded.add(p - 1);
      if (p < numPages) expanded.add(p + 1);
    });
    setVisiblePages((prev) => {
      if (prev.size === expanded.size) {
        let same = true;
        for (const x of expanded) if (!prev.has(x)) { same = false; break; }
        if (same) return prev;
      }
      return expanded;
    });
  }, [pageMetas, numPages, onPositionChange]);

  const handleScroll = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = window.requestAnimationFrame(computePosition);
  }, [computePosition]);

  // pageMetas 变化（首次就绪 / scale 改变 / 容器宽度改变，比如 AI 边栏 narrow/wide/overlay 切换）
  // → 先按 lastReportedRef 把 scrollTop 恢复到原阅读位置（与反推算法对称），再重算 currentPage / visiblePages。
  // 不区分 scale vs containerWidth：两条路径都会让坐标系整体重算，恢复逻辑相同。
  useEffect(() => {
    if (pageMetas.length === 0) return;
    const el = containerRef.current;
    const last = lastReportedRef.current;
    if (el && last) {
      const meta = pageMetas.find((m) => m.pageNum === last.page);
      if (meta) {
        const desiredCenter = meta.top + last.offset * meta.height;
        const max = Math.max(0, el.scrollHeight - el.clientHeight);
        el.scrollTop = Math.max(0, Math.min(max, desiredCenter - el.clientHeight / 2));
      }
    }
    computePosition();
  }, [pageMetas, computePosition]);

  // ---- pendingScrollTarget 消费 ----
  useEffect(() => {
    if (!pendingScrollTarget) return;
    if (pageMetas.length === 0) return;
    const el = containerRef.current;
    if (!el) return;
    const meta = pageMetas.find((m) => m.pageNum === pendingScrollTarget.page);
    if (!meta) {
      onScrollTargetConsumed();
      return;
    }
    // 让 (page, offset) 出现在 viewport 中心（与反推算法对称）
    const desiredCenter = meta.top + pendingScrollTarget.offset * meta.height;
    const max = Math.max(0, el.scrollHeight - el.clientHeight);
    el.scrollTop = Math.max(0, Math.min(max, desiredCenter - el.clientHeight / 2));
    onScrollTargetConsumed();
  }, [pendingScrollTarget, pageMetas, onScrollTargetConsumed]);

  // ---- Ctrl+wheel 缩放（原生监听以确保 preventDefault 生效）----
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      if (e.deltaY < 0) onZoomIn();
      else onZoomOut();
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [onZoomIn, onZoomOut]);

  // ---- 键盘：Esc + PageUp/PageDown ----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      const el = containerRef.current;
      if (e.key === 'Escape') {
        if (isSelecting) {
          onSelectionModeExit();
          setDrag(null);
        } else if (selectedArea) {
          onSelectionChange(null);
        }
        return;
      }
      if (!el) return;
      if (e.key === 'PageDown') {
        e.preventDefault();
        el.scrollBy({ top: el.clientHeight * 0.95, behavior: 'smooth' });
      } else if (e.key === 'PageUp') {
        e.preventDefault();
        el.scrollBy({ top: -el.clientHeight * 0.95, behavior: 'smooth' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isSelecting, selectedArea, onSelectionChange, onSelectionModeExit]);

  // ---- V1.1.4：跨页 Selection 抓取已迁出至 useTextSelection hook（由父组件调用）。----
  // PDFViewer 仅负责 textLayer DOM 渲染；mouseup 监听由 hook 在同一 container 上挂载。

  // ---- 框选事件（起点页 clamp）----
  const findPageForY = useCallback(
    (clientY: number): PageMeta | null => {
      const el = containerRef.current;
      if (!el || pageMetas.length === 0) return null;
      const rect = el.getBoundingClientRect();
      const y = clientY - rect.top + el.scrollTop;
      for (const m of pageMetas) {
        if (y >= m.top && y <= m.top + m.height) return m;
      }
      // 落在 gap 中：归到更近的一边
      if (y < pageMetas[0].top) return pageMetas[0];
      return pageMetas[pageMetas.length - 1];
    },
    [pageMetas],
  );

  const getRelativeCoordsInPage = useCallback(
    (clientX: number, clientY: number, meta: PageMeta) => {
      const el = containerRef.current;
      if (!el) return { x: 0, y: 0 };
      const rect = el.getBoundingClientRect();
      const xInContainer = clientX - rect.left + el.scrollLeft;
      const yInContainer = clientY - rect.top + el.scrollTop;
      const innerWidth = el.clientWidth;
      const pageLeft = (innerWidth - meta.width) / 2;
      const x = (xInContainer - pageLeft) / meta.width;
      const y = (yInContainer - meta.top) / meta.height;
      return {
        x: Math.max(0, Math.min(1, x)),
        y: Math.max(0, Math.min(1, y)),
      };
    },
    [],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (!isSelecting) return;
      const meta = findPageForY(e.clientY);
      if (!meta) return;
      const coords = getRelativeCoordsInPage(e.clientX, e.clientY, meta);
      setDrag({
        page: meta.pageNum,
        startX: coords.x,
        startY: coords.y,
        currentX: coords.x,
        currentY: coords.y,
      });
      onSelectionChange(null);
    },
    [isSelecting, findPageForY, getRelativeCoordsInPage, onSelectionChange],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!drag || !isSelecting) return;
      const meta = pageMetas.find((m) => m.pageNum === drag.page);
      if (!meta) return;
      // 即便鼠标已经移动到另一页，仍以起点页坐标系 clamp（D-V113-6）
      const coords = getRelativeCoordsInPage(e.clientX, e.clientY, meta);
      setDrag((prev) => (prev ? { ...prev, currentX: coords.x, currentY: coords.y } : prev));
    },
    [drag, isSelecting, pageMetas, getRelativeCoordsInPage],
  );

  const handleMouseUp = useCallback(() => {
    if (!drag || !isSelecting) return;
    const x = Math.min(drag.startX, drag.currentX);
    const y = Math.min(drag.startY, drag.currentY);
    const width = Math.abs(drag.currentX - drag.startX);
    const height = Math.abs(drag.currentY - drag.startY);
    const startPage = drag.page;
    setDrag(null);
    if (width > 0.01 && height > 0.01) {
      onSelectionChange({ page: startPage, x, y, width, height });
    } else {
      onSelectionChange(null);
    }
    onSelectionModeExit();
  }, [drag, isSelecting, onSelectionChange, onSelectionModeExit]);

  const dragRectForPage = useCallback(
    (pageNum: number) => {
      if (!drag || drag.page !== pageNum) return null;
      return {
        left: Math.min(drag.startX, drag.currentX),
        top: Math.min(drag.startY, drag.currentY),
        width: Math.abs(drag.currentX - drag.startX),
        height: Math.abs(drag.currentY - drag.startY),
      };
    },
    [drag],
  );

  const selectionRectForPage = useCallback(
    (pageNum: number) => {
      if (drag) return null; // 拖动时只显示 dragRect
      if (!selectedArea || selectedArea.page !== pageNum) return null;
      return {
        x: selectedArea.x,
        y: selectedArea.y,
        width: selectedArea.width,
        height: selectedArea.height,
      };
    },
    [drag, selectedArea],
  );

  const hasReadyPages = pdfDoc && !isLoading && pageMetas.length > 0;

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      className="flex-1 overflow-auto bg-stone-100 outline-none"
      style={{
        cursor:
          cursorMode === 'screenshot' || isSelecting
            ? 'crosshair'
            : cursorMode === 'text'
              ? 'text'
              : 'default',
      }}
    >
      {isLoading && (
        <div className="flex flex-col items-center justify-center h-full gap-3 text-stone-400">
          <i className="ri-loader-4-line animate-spin text-3xl"></i>
          <p className="text-sm">Loading PDF...</p>
        </div>
      )}

      {error && (
        <div className="flex flex-col items-center justify-center h-full gap-3 text-red-500">
          <i className="ri-error-warning-line text-3xl"></i>
          <p className="text-sm">{error}</p>
        </div>
      )}

      {!pdfDoc && !isLoading && !error && (
        <div className="flex flex-col items-center justify-center h-full gap-4 text-stone-400">
          <div className="w-20 h-20 flex items-center justify-center rounded-2xl bg-stone-200">
            <i className="ri-file-pdf-2-line text-4xl text-stone-400"></i>
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-stone-500">No PDF opened</p>
            <p className="text-xs text-stone-400 mt-1">
              Click &quot;Open PDF&quot; in the toolbar to get started
            </p>
          </div>
        </div>
      )}

      {hasReadyPages && (
        <div className="relative" style={{ height: totalHeight, minHeight: '100%' }}>
          {pageMetas.map((meta) => (
            <div
              key={meta.pageNum}
              className="absolute left-0 right-0 flex justify-center"
              style={{ top: meta.top, height: meta.height }}
            >
              <PDFPage
                pdfDoc={pdfDoc!}
                pageNum={meta.pageNum}
                width={meta.width}
                height={meta.height}
                visible={visiblePages.has(meta.pageNum)}
                dragRect={dragRectForPage(meta.pageNum)}
                selectionRect={selectionRectForPage(meta.pageNum)}
                cursorMode={cursorMode}
                onScanPageDetected={onScanPageDetected}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

interface PDFPageProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy;
  pageNum: number;
  width: number;
  height: number;
  visible: boolean;
  dragRect: { left: number; top: number; width: number; height: number } | null;
  selectionRect: { x: number; y: number; width: number; height: number } | null;
  cursorMode: 'off' | 'text' | 'screenshot';
  onScanPageDetected?: (pageNum: number) => void;
}

const PDFPage = memo(function PDFPage({
  pdfDoc,
  pageNum,
  width,
  height,
  visible,
  dragRect,
  selectionRect,
  cursorMode,
  onScanPageDetected,
}: PDFPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);
  // V1.1.4 PoC: TextLayer 实例引用（pdfjs-dist 4.x 引入的类）
  // 类型用 InstanceType 推导而非 import（避免无 default export 的 TextLayer 类型路径声明摩擦）
  const textLayerInstanceRef = useRef<InstanceType<typeof pdfjsLib.TextLayer> | null>(null);

  useEffect(() => {
    if (!visible) return;
    if (width <= 0 || height <= 0) return;
    let cancelled = false;
    (async () => {
      try {
        const page = await pdfDoc.getPage(pageNum);
        const baseVp = page.getViewport({ scale: 1 });
        const renderScale = width / baseVp.width;
        const dpr = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale: renderScale * dpr });
        const canvas = canvasRef.current;
        if (!canvas || cancelled) return;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        if (renderTaskRef.current) renderTaskRef.current.cancel();
        const ctx = canvas.getContext('2d')!;
        renderTaskRef.current = page.render({ canvasContext: ctx, viewport });
        try {
          await renderTaskRef.current.promise;
        } catch (err: unknown) {
          const name = (err as { name?: string })?.name;
          if (name !== 'RenderingCancelledException') console.error('render error:', err);
        }

        // V1.1.4：textLayer 常态渲染 + 扫描版检测（textContent.trim()==='' 视为扫描版/无文本层）
        if (!cancelled) {
          const textLayerEl = textLayerRef.current;
          if (textLayerEl) {
            try {
              // pdfjs 4.x TextLayer 把 span 的 left/top/fontSize 都写成
              // calc(var(--scale-factor) * Xpx)，必须在容器上注入 --scale-factor
              // 否则 calc() 解析为 0 → 所有字堆叠在左上角且 font-size 为 0。
              // 这里用 renderScale（不含 dpr，因为我们用 CSS 像素布局 textLayer）。
              const tlViewport = page.getViewport({ scale: renderScale });
              textLayerEl.style.setProperty('--scale-factor', String(renderScale));
              const textContentSource = page.streamTextContent({ disableNormalization: true });
              // 清空旧内容（pageNum 不变但 width/height 变化会重入此 effect）
              if (textLayerInstanceRef.current) {
                try { textLayerInstanceRef.current.cancel(); } catch { /* ignore */ }
                textLayerInstanceRef.current = null;
              }
              while (textLayerEl.firstChild) textLayerEl.removeChild(textLayerEl.firstChild);
              const tl = new pdfjsLib.TextLayer({
                textContentSource,
                container: textLayerEl,
                viewport: tlViewport,
              });
              textLayerInstanceRef.current = tl;
              await tl.render();
              if (cancelled) return;
              // 扫描版检测：textLayer 为空 → 上报给父组件（FE-6 Toast + cursorMode 拦截）
              const trimmed = (textLayerEl.textContent || '').trim();
              if (trimmed === '') {
                onScanPageDetected?.(pageNum);
              }
            } catch (err: unknown) {
              const name = (err as { name?: string })?.name;
              if (name !== 'AbortException') {
                console.error(`textLayer 渲染失败 page=${pageNum}:`, err);
              }
            }
          }
        }
      } catch (err) {
        console.error('page render error:', err);
      }
    })();
    return () => {
      cancelled = true;
      if (renderTaskRef.current) renderTaskRef.current.cancel();
      if (textLayerInstanceRef.current) {
        try { textLayerInstanceRef.current.cancel(); } catch { /* ignore */ }
        textLayerInstanceRef.current = null;
      }
    };
  }, [pdfDoc, pageNum, width, height, visible, onScanPageDetected]);

  return (
    <div
      data-page={pageNum}
      className="relative bg-white shadow-md"
      style={{ width, height }}
    >
      {visible ? (
        <canvas ref={canvasRef} className="block" />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-stone-300 text-xs select-none">
          {pageNum}
        </div>
      )}
      {/* V1.1.4：textLayer 常态渲染，pointer-events 由 cursorMode 控制；
          只有 'text' 模式才接收鼠标事件以触发原生文本选区。
          注意：opacity 必须为 1 让浏览器原生 ::selection 高亮可见；
          span 自身 color:transparent（来自 .textLayer 全局样式）保证文字隐形不遮挡 canvas。*/}
      <div
        ref={textLayerRef}
        className="textLayer"
        style={{
          pointerEvents: cursorMode === 'text' ? 'auto' : 'none',
          cursor: cursorMode === 'text' ? 'text' : 'inherit',
        }}
      />
      {dragRect && (
        <div
          className="absolute pointer-events-none border-2 border-amber-400 bg-amber-400/15"
          style={{
            left: `${dragRect.left * 100}%`,
            top: `${dragRect.top * 100}%`,
            width: `${dragRect.width * 100}%`,
            height: `${dragRect.height * 100}%`,
          }}
        />
      )}
      {selectionRect && (
        <div
          className="absolute pointer-events-none border-2 border-amber-500 bg-amber-400/10"
          style={{
            left: `${selectionRect.x * 100}%`,
            top: `${selectionRect.y * 100}%`,
            width: `${selectionRect.width * 100}%`,
            height: `${selectionRect.height * 100}%`,
          }}
        />
      )}
    </div>
  );
});

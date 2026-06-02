import { useRef, useEffect, useState, useCallback } from 'react';
import type * as pdfjsLib from 'pdfjs-dist';

interface PDFViewerProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  currentPage: number;
  scale: number;
  isLoading: boolean;
  error: string | null;
  onSelectionChange: (selection: { x: number; y: number; width: number; height: number } | null) => void;
  selectedArea: { x: number; y: number; width: number; height: number } | null;
  onNextPage: () => void;
  onPrevPage: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  isSelecting: boolean;
  onSelectionModeExit: () => void;
}

interface SelectionState {
  startX: number;
  startY: number;
  currentX: number;
  currentY: number;
  isDragging: boolean;
}

export default function PDFViewer({
  pdfDoc,
  currentPage,
  scale,
  isLoading,
  error,
  onSelectionChange,
  selectedArea,
  onNextPage,
  onPrevPage,
  onZoomIn,
  onZoomOut,
  isSelecting,
  onSelectionModeExit,
}: PDFViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<SelectionState>({
    startX: 0,
    startY: 0,
    currentX: 0,
    currentY: 0,
    isDragging: false,
  });
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const boundaryHitRef = useRef<{ direction: 'up' | 'down'; timer: number } | null>(null);

  const clearBoundaryHit = useCallback(() => {
    if (boundaryHitRef.current) {
      window.clearTimeout(boundaryHitRef.current.timer);
      boundaryHitRef.current = null;
    }
  }, []);

  useEffect(() => clearBoundaryHit, [clearBoundaryHit]);

  useEffect(() => {
    const updateSize = () => {
      if (containerRef.current) {
        setContainerSize({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
    window.addEventListener('resize', updateSize);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateSize);
    };
  }, []);

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current || containerSize.width === 0 || containerSize.height === 0) return;

    const renderPage = async () => {
      try {
        const page = await pdfDoc.getPage(currentPage);
        const baseViewport = page.getViewport({ scale: 1 });
        const padding = 48;
        const fitScale = Math.min(
          (containerSize.width - padding) / baseViewport.width,
          (containerSize.height - padding) / baseViewport.height,
        ) * 0.95;
        const actualScale = Math.max(0.1, fitScale * scale);
        const viewport = page.getViewport({ scale: actualScale });

        const canvas = canvasRef.current!;
        canvas.width = viewport.width;
        canvas.height = viewport.height;

        if (renderTaskRef.current) {
          renderTaskRef.current.cancel();
        }

        const context = canvas.getContext('2d')!;
        const renderContext = {
          canvasContext: context,
          viewport,
        };

        renderTaskRef.current = page.render(renderContext);
        await renderTaskRef.current.promise;
      } catch (err: any) {
        if (err?.name !== 'RenderingCancelledException') {
          console.error('Render error:', err);
        }
      }
    };

    renderPage();

    return () => {
      if (renderTaskRef.current) {
        renderTaskRef.current.cancel();
      }
    };
  }, [pdfDoc, currentPage, scale, containerSize]);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
      containerRef.current.scrollLeft = 0;
    }
    clearBoundaryHit();
  }, [currentPage, clearBoundaryHit]);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        if (e.deltaY < 0) {
          onZoomIn();
        } else {
          onZoomOut();
        }
        return;
      }

      const container = containerRef.current;
      if (!container) return;

      const canScrollVertically = container.scrollHeight > container.clientHeight + 1;

      if (!canScrollVertically) {
        e.preventDefault();
        clearBoundaryHit();
        if (e.deltaY > 0) {
          onNextPage();
        } else if (e.deltaY < 0) {
          onPrevPage();
        }
        return;
      }

      const direction: 'down' | 'up' = e.deltaY > 0 ? 'down' : 'up';
      const atTop = container.scrollTop <= 0;
      const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 1;
      const atBoundary = (direction === 'down' && atBottom) || (direction === 'up' && atTop);

      if (!atBoundary) {
        clearBoundaryHit();
        return;
      }

      const hit = boundaryHitRef.current;
      if (hit && hit.direction === direction) {
        e.preventDefault();
        clearBoundaryHit();
        if (direction === 'down') {
          onNextPage();
        } else {
          onPrevPage();
        }
        return;
      }

      e.preventDefault();
      clearBoundaryHit();
      const timer = window.setTimeout(() => {
        boundaryHitRef.current = null;
      }, 300);
      boundaryHitRef.current = { direction, timer };
    },
    [onNextPage, onPrevPage, onZoomIn, onZoomOut, clearBoundaryHit],
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isSelecting) {
          onSelectionModeExit();
          setSelection((prev) => ({ ...prev, isDragging: false }));
        } else if (selectedArea) {
          onSelectionChange(null);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSelecting, selectedArea, onSelectionModeExit, onSelectionChange]);

  const getRelativeCoords = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return {
        x: (clientX - rect.left) / rect.width,
        y: (clientY - rect.top) / rect.height,
      };
    },
    [],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (!isSelecting) return;
      const coords = getRelativeCoords(e.clientX, e.clientY);
      setSelection({
        startX: coords.x,
        startY: coords.y,
        currentX: coords.x,
        currentY: coords.y,
        isDragging: true,
      });
      onSelectionChange(null);
    },
    [getRelativeCoords, onSelectionChange, isSelecting],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!selection.isDragging || !isSelecting) return;
      const coords = getRelativeCoords(e.clientX, e.clientY);
      setSelection((prev) => ({
        ...prev,
        currentX: coords.x,
        currentY: coords.y,
      }));
    },
    [selection.isDragging, getRelativeCoords, isSelecting],
  );

  const handleMouseUp = useCallback(() => {
    if (!selection.isDragging || !isSelecting) return;
    setSelection((prev) => ({ ...prev, isDragging: false }));

    const x = Math.min(selection.startX, selection.currentX);
    const y = Math.min(selection.startY, selection.currentY);
    const width = Math.abs(selection.currentX - selection.startX);
    const height = Math.abs(selection.currentY - selection.startY);

    if (width > 0.01 && height > 0.01) {
      onSelectionChange({ x, y, width, height });
    } else {
      onSelectionChange(null);
    }

    onSelectionModeExit();
  }, [selection, onSelectionChange, onSelectionModeExit, isSelecting]);

  const selectionRect = selection.isDragging
    ? {
        left: Math.min(selection.startX, selection.currentX),
        top: Math.min(selection.startY, selection.currentY),
        width: Math.abs(selection.currentX - selection.startX),
        height: Math.abs(selection.currentY - selection.startY),
      }
    : null;

  return (
    <div
      ref={containerRef}
      onWheel={handleWheel}
      className="flex-1 overflow-auto bg-stone-100"
    >
      <div className="min-h-full flex items-start justify-center p-6">
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

        {pdfDoc && !isLoading && (
          <div
            className="relative inline-block"
            style={{ cursor: isSelecting ? 'crosshair' : 'default' }}
          >
            <canvas
              ref={canvasRef}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              className="shadow-lg bg-white"
            />

            {selectionRect && (
              <div
                className="absolute pointer-events-none border-2 border-amber-400 bg-amber-400/15"
                style={{
                  left: `${selectionRect.left * 100}%`,
                  top: `${selectionRect.top * 100}%`,
                  width: `${selectionRect.width * 100}%`,
                  height: `${selectionRect.height * 100}%`,
                }}
              />
            )}

            {selectedArea && !selection.isDragging && (
              <div
                className="absolute pointer-events-none border-2 border-amber-500 bg-amber-400/10"
                style={{
                  left: `${selectedArea.x * 100}%`,
                  top: `${selectedArea.y * 100}%`,
                  width: `${selectedArea.width * 100}%`,
                  height: `${selectedArea.height * 100}%`,
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
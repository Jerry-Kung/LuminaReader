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
}: PDFViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [selection, setSelection] = useState<SelectionState>({
    startX: 0,
    startY: 0,
    currentX: 0,
    currentY: 0,
    isDragging: false,
  });
  const renderTaskRef = useRef<pdfjsLib.RenderTask | null>(null);

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;

    const renderPage = async () => {
      try {
        const page = await pdfDoc.getPage(currentPage);
        const viewport = page.getViewport({ scale });

        const canvas = canvasRef.current!;
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        setCanvasSize({ width: viewport.width, height: viewport.height });

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
  }, [pdfDoc, currentPage, scale]);

  const getRelativeCoords = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return { x: 0, y: 0 };
      const rect = canvas.getBoundingClientRect();
      return {
        x: (clientX - rect.left) * (canvas.width / rect.width),
        y: (clientY - rect.top) * (canvas.height / rect.height),
      };
    },
    [],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
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
    [getRelativeCoords, onSelectionChange],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!selection.isDragging) return;
      const coords = getRelativeCoords(e.clientX, e.clientY);
      setSelection((prev) => ({
        ...prev,
        currentX: coords.x,
        currentY: coords.y,
      }));
    },
    [selection.isDragging, getRelativeCoords],
  );

  const handleMouseUp = useCallback(() => {
    if (!selection.isDragging) return;
    setSelection((prev) => ({ ...prev, isDragging: false }));

    const x = Math.min(selection.startX, selection.currentX);
    const y = Math.min(selection.startY, selection.currentY);
    const width = Math.abs(selection.currentX - selection.startX);
    const height = Math.abs(selection.currentY - selection.startY);

    if (width > 10 && height > 10) {
      onSelectionChange({ x, y, width, height });
    } else {
      onSelectionChange(null);
    }
  }, [selection, onSelectionChange]);

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
      className="flex-1 overflow-auto bg-stone-100 flex items-start justify-center p-6"
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

      {pdfDoc && !isLoading && (
        <div className="relative inline-block" style={{ cursor: 'crosshair' }}>
          <canvas
            ref={canvasRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            className="shadow-lg bg-white"
            style={{
              maxWidth: '100%',
              height: 'auto',
            }}
          />

          {selectionRect && (
            <div
              className="absolute pointer-events-none border-2 border-amber-400 bg-amber-400/15"
              style={{
                left: `${(selectionRect.left / canvasSize.width) * 100}%`,
                top: `${(selectionRect.top / canvasSize.height) * 100}%`,
                width: `${(selectionRect.width / canvasSize.width) * 100}%`,
                height: `${(selectionRect.height / canvasSize.height) * 100}%`,
              }}
            />
          )}

          {selectedArea && !selection.isDragging && (
            <div
              className="absolute pointer-events-none border-2 border-amber-500 bg-amber-400/10"
              style={{
                left: `${(selectedArea.x / canvasSize.width) * 100}%`,
                top: `${(selectedArea.y / canvasSize.height) * 100}%`,
                width: `${(selectedArea.width / canvasSize.width) * 100}%`,
                height: `${(selectedArea.height / canvasSize.height) * 100}%`,
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
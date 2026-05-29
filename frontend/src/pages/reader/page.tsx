import { useState, useRef, useCallback } from 'react';
import { usePDF } from '@/hooks/usePDF';
import { translateSelection, TranslateApiError } from '@/services/api';
import Toolbar from './components/Toolbar';
import PDFViewer from './components/PDFViewer';
import AIAssistantPanel from './components/AIAssistantPanel';

type TaskType = 'translate' | 'explain';

interface AIResult {
  id: number;
  type: TaskType;
  imageBase64: string;
  text: string;
  timestamp: number;
}

interface SelectedArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

export default function ReaderPage() {
  const {
    pdfDoc,
    numPages,
    currentPage,
    scale,
    isLoading,
    error: pdfError,
    fileName,
    loadPDF,
    goToPage,
    nextPage,
    prevPage,
    zoomIn,
    zoomOut,
  } = usePDF();

  const [isSelecting, setIsSelecting] = useState(false);
  const [selectedArea, setSelectedArea] = useState<SelectedArea | null>(null);
  const [aiResults, setAiResults] = useState<AIResult[]>([]);
  const [isAIWorking, setIsAIWorking] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [activeTaskType, setActiveTaskType] = useState<TaskType>('translate');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleOpenFile = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file && file.type === 'application/pdf') {
        loadPDF(file);
        setSelectedArea(null);
        setAiResults([]);
        setAiError(null);
        setIsSelecting(false);
      } else if (file) {
        loadPDF(file);
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    },
    [loadPDF],
  );

  const handleToggleSelectionMode = useCallback(() => {
    setIsSelecting((prev) => !prev);
  }, []);

  const handleSelectionModeExit = useCallback(() => {
    setIsSelecting(false);
  }, []);

  const handleSelectionChange = useCallback((area: SelectedArea | null) => {
    setSelectedArea(area);
  }, []);

  const handleAIRequest = useCallback(
    async (taskType: TaskType) => {
      if (!selectedArea || !pdfDoc) return;

      setIsAIWorking(true);
      setAiError(null);

      try {
        const page = await pdfDoc.getPage(currentPage);
        const captureScale = 2.0;
        const captureViewport = page.getViewport({ scale: captureScale });
        const baseViewport = page.getViewport({ scale: 1 });

        const canvas = document.createElement('canvas');
        canvas.width = captureViewport.width;
        canvas.height = captureViewport.height;
        const ctx = canvas.getContext('2d')!;
        await page.render({ canvasContext: ctx, viewport: captureViewport }).promise;

        const captureX = selectedArea.x * captureViewport.width;
        const captureY = selectedArea.y * captureViewport.height;
        const captureWidth = selectedArea.width * captureViewport.width;
        const captureHeight = selectedArea.height * captureViewport.height;

        const offCanvas = document.createElement('canvas');
        offCanvas.width = Math.max(1, Math.round(captureWidth));
        offCanvas.height = Math.max(1, Math.round(captureHeight));
        const offCtx = offCanvas.getContext('2d')!;

        offCtx.drawImage(
          canvas,
          captureX,
          captureY,
          captureWidth,
          captureHeight,
          0,
          0,
          offCanvas.width,
          offCanvas.height,
        );

        const imageDataUrl = offCanvas.toDataURL('image/png');
        const imageBase64 = imageDataUrl.replace(/^data:image\/png;base64,/, '');

        const result = await translateSelection(
          {
            page: currentPage,
            x: selectedArea.x * baseViewport.width,
            y: selectedArea.y * baseViewport.height,
            w: selectedArea.width * baseViewport.width,
            h: selectedArea.height * baseViewport.height,
            dpi: 72 * captureScale,
          },
          {
            data: imageBase64,
            width: offCanvas.width,
            height: offCanvas.height,
          },
          { targetLang: 'zh-CN', taskType },
        );

        setAiResults((prev) => [
          {
            id: Date.now(),
            type: taskType,
            imageBase64: imageDataUrl,
            text: result.text,
            timestamp: Date.now(),
          },
          ...prev,
        ]);
      } catch (err: any) {
        const msg =
          err instanceof TranslateApiError
            ? `[${err.code}] ${err.message}`
            : err?.message || 'AI request failed. Please try again.';
        setAiError(msg);
      } finally {
        setIsAIWorking(false);
      }
    },
    [selectedArea, pdfDoc, currentPage],
  );

  return (
    <div className="h-screen flex flex-col bg-stone-50">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        onChange={handleFileChange}
        className="hidden"
      />

      <Toolbar
        fileName={fileName}
        numPages={numPages}
        currentPage={currentPage}
        scale={scale}
        hasSelection={!!selectedArea}
        isAIWorking={isAIWorking}
        isSelecting={isSelecting}
        activeTaskType={activeTaskType}
        onOpenFile={handleOpenFile}
        onPrevPage={prevPage}
        onNextPage={nextPage}
        onGoToPage={goToPage}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onAIRequest={handleAIRequest}
        onToggleSelectionMode={handleToggleSelectionMode}
        onTaskTypeChange={setActiveTaskType}
      />

      <div className="flex-1 flex overflow-hidden">
        <PDFViewer
          pdfDoc={pdfDoc}
          currentPage={currentPage}
          scale={scale}
          isLoading={isLoading}
          error={pdfError}
          onSelectionChange={handleSelectionChange}
          selectedArea={selectedArea}
          onNextPage={nextPage}
          onPrevPage={prevPage}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          isSelecting={isSelecting}
          onSelectionModeExit={handleSelectionModeExit}
        />
        <AIAssistantPanel
          results={aiResults}
          isAIWorking={isAIWorking}
          error={aiError}
        />
      </div>
    </div>
  );
}

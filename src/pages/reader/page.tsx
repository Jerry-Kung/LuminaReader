import { useState, useRef, useCallback } from 'react';
import { usePDF } from '@/hooks/usePDF';
import { translateSelection } from '@/services/api';
import Toolbar from './components/Toolbar';
import PDFViewer from './components/PDFViewer';
import TranslationPanel from './components/TranslationPanel';

interface TranslationResult {
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

  const [selectedArea, setSelectedArea] = useState<SelectedArea | null>(null);
  const [translationResults, setTranslationResults] = useState<TranslationResult[]>([]);
  const [isTranslating, setIsTranslating] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
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
        setTranslationResults([]);
        setTranslationError(null);
      } else if (file) {
        // We don't have a good way to show error in the hook, but the hook handles it
        loadPDF(file);
      }
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    },
    [loadPDF],
  );

  const handleTranslate = useCallback(async () => {
    if (!selectedArea || !pdfDoc) return;

    setIsTranslating(true);
    setTranslationError(null);

    try {
      const page = await pdfDoc.getPage(currentPage);
      const viewport = page.getViewport({ scale });

      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext('2d')!;

      await page.render({ canvasContext: ctx, viewport }).promise;

      const offCanvas = document.createElement('canvas');
      offCanvas.width = selectedArea.width;
      offCanvas.height = selectedArea.height;
      const offCtx = offCanvas.getContext('2d')!;

      offCtx.drawImage(
        canvas,
        selectedArea.x,
        selectedArea.y,
        selectedArea.width,
        selectedArea.height,
        0,
        0,
        selectedArea.width,
        selectedArea.height,
      );

      const imageBase64 = offCanvas.toDataURL('image/png');

      const result = await translateSelection(imageBase64, 'zh-CN');

      setTranslationResults((prev) => [
        { text: result.translated_text, timestamp: Date.now() },
        ...prev,
      ]);
    } catch (err: any) {
      setTranslationError(err.message || 'Translation failed. Please try again.');
    } finally {
      setIsTranslating(false);
    }
  }, [selectedArea, pdfDoc, currentPage, scale]);

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
        isTranslating={isTranslating}
        onOpenFile={handleOpenFile}
        onPrevPage={prevPage}
        onNextPage={nextPage}
        onGoToPage={goToPage}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onTranslate={handleTranslate}
      />

      <div className="flex-1 flex overflow-hidden">
        <PDFViewer
          pdfDoc={pdfDoc}
          currentPage={currentPage}
          scale={scale}
          isLoading={isLoading}
          error={pdfError}
          onSelectionChange={setSelectedArea}
          selectedArea={selectedArea}
        />
        <TranslationPanel
          results={translationResults}
          isTranslating={isTranslating}
          error={translationError}
        />
      </div>
    </div>
  );
}
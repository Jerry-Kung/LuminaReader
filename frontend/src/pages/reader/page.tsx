import { useState, useRef, useCallback } from 'react';
import { usePDF } from '@/hooks/usePDF';
import { runTask, runFollowUp, clearSession, TranslateApiError, type TaskType } from '@/services/api';
import Toolbar from './components/Toolbar';
import PDFViewer from './components/PDFViewer';
import AIAssistantPanel from './components/AIAssistantPanel';

export interface Message {
  id: number;
  role: 'user' | 'ai';
  text: string;
  timestamp: number;
  isLoading?: boolean;
  isError?: boolean;
  errorText?: string;
}

export interface AIResult {
  id: number;
  type: TaskType;
  sessionId: string;
  imageBase64: string;
  messages: Message[];
  timestamp: number;
  collapsed: boolean;
}

interface SelectedArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface CaptureResult {
  dataUrl: string;
  base64: string;
  width: number;
  height: number;
  selection: { page: number; x: number; y: number; w: number; h: number; dpi: number };
}

function formatError(err: unknown): string {
  if (err instanceof TranslateApiError) {
    return `[${err.code}] ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return 'AI request failed. Please try again.';
}

let msgSeq = 1;
function nextMsgId(): number {
  return Date.now() * 1000 + (msgSeq++ % 1000);
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
  const [userInput, setUserInput] = useState('');
  const [panelMode, setPanelMode] = useState<'narrow' | 'wide' | 'overlay'>('narrow');
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
        setUserInput('');
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

  // Render the selected region to a PNG and compute the PDF user-space selection metadata.
  const captureImage = useCallback(async (): Promise<CaptureResult | null> => {
    if (!selectedArea || !pdfDoc) return null;
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

    const dataUrl = offCanvas.toDataURL('image/png');
    return {
      dataUrl,
      base64: dataUrl.replace(/^data:image\/png;base64,/, ''),
      width: offCanvas.width,
      height: offCanvas.height,
      selection: {
        page: currentPage,
        x: selectedArea.x * baseViewport.width,
        y: selectedArea.y * baseViewport.height,
        w: selectedArea.width * baseViewport.width,
        h: selectedArea.height * baseViewport.height,
        dpi: 72 * captureScale,
      },
    };
  }, [selectedArea, pdfDoc, currentPage]);

  // First turn: send the screenshot; backend extracts text into a new session and runs the task.
  const handleAIRequest = useCallback(
    async (taskType: TaskType, inputText?: string) => {
      if (!selectedArea || !pdfDoc) return;

      setIsAIWorking(true);
      setAiError(null);

      const cardId = nextMsgId();
      const loadingId = nextMsgId();
      const trimmedInput = inputText?.trim();

      try {
        const capture = await captureImage();
        if (!capture) throw new Error('Failed to capture image');

        const initialMessages: Message[] = [];
        if (trimmedInput) {
          initialMessages.push({
            id: nextMsgId(),
            role: 'user',
            text: trimmedInput,
            timestamp: Date.now(),
          });
        }
        initialMessages.push({
          id: loadingId,
          role: 'ai',
          text: '',
          timestamp: Date.now(),
          isLoading: true,
        });

        setAiResults((prev) => [
          ...prev.map((r) => (r.collapsed ? r : { ...r, collapsed: true })),
          {
            id: cardId,
            type: taskType,
            sessionId: '',
            imageBase64: capture.dataUrl,
            messages: initialMessages,
            timestamp: Date.now(),
            collapsed: false,
          },
        ]);

        const result = await runTask(taskType, capture.selection, {
          data: capture.base64,
          width: capture.width,
          height: capture.height,
        }, { targetLang: 'zh-CN', userQuestion: trimmedInput });

        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const filtered = updated[idx].messages.filter((m) => m.id !== loadingId);
          updated[idx] = {
            ...updated[idx],
            sessionId: result.sessionId,
            messages: [
              ...filtered,
              { id: nextMsgId(), role: 'ai', text: result.text, timestamp: Date.now() },
            ],
          };
          return updated;
        });
      } catch (err: unknown) {
        const msg = formatError(err);
        setAiError(msg);
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const filtered = updated[idx].messages.filter((m) => m.id !== loadingId);
          updated[idx] = {
            ...updated[idx],
            messages: [
              ...filtered,
              {
                id: nextMsgId(),
                role: 'ai',
                text: 'Request failed',
                timestamp: Date.now(),
                isError: true,
                errorText: msg,
              },
            ],
          };
          return updated;
        });
      } finally {
        setIsAIWorking(false);
      }
    },
    [selectedArea, pdfDoc, captureImage],
  );

  // Follow-up turn: text-driven only — send sessionId + question, no image (Scheme D).
  const handleFollowUp = useCallback(
    async (cardId: number, text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      const card = aiResults.find((r) => r.id === cardId);
      if (!card || !card.sessionId) return;

      const loadingId = nextMsgId();

      setAiResults((prev) => {
        const idx = prev.findIndex((r) => r.id === cardId);
        if (idx === -1) return prev;
        const updated = [...prev];
        updated[idx] = {
          ...updated[idx],
          messages: [
            ...updated[idx].messages,
            { id: nextMsgId(), role: 'user', text: trimmed, timestamp: Date.now() },
            { id: loadingId, role: 'ai', text: '', timestamp: Date.now(), isLoading: true },
          ],
        };
        return updated;
      });

      try {
        const result = await runFollowUp(card.type, card.sessionId, trimmed, { targetLang: 'zh-CN' });

        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const filtered = updated[idx].messages.filter((m) => m.id !== loadingId);
          updated[idx] = {
            ...updated[idx],
            messages: [
              ...filtered,
              { id: nextMsgId(), role: 'ai', text: result.text, timestamp: Date.now() },
            ],
          };
          return updated;
        });
      } catch (err: unknown) {
        const msg = formatError(err);
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const filtered = updated[idx].messages.filter((m) => m.id !== loadingId);
          updated[idx] = {
            ...updated[idx],
            messages: [
              ...filtered,
              {
                id: nextMsgId(),
                role: 'ai',
                text: 'Request failed',
                timestamp: Date.now(),
                isError: true,
                errorText: msg,
              },
            ],
          };
          return updated;
        });
      }
    },
    [aiResults],
  );

  // Clear conversation: release the backend session first, then drop the card (R-V102-7).
  const handleClearCard = useCallback(
    async (cardId: number) => {
      const card = aiResults.find((r) => r.id === cardId);
      if (card?.sessionId) {
        try {
          await clearSession(card.sessionId);
        } catch {
          // Session release failed (network/server); still clear the local card.
        }
      }
      setAiResults((prev) => prev.filter((r) => r.id !== cardId));
    },
    [aiResults],
  );

  const handleToggleCollapse = useCallback((cardId: number) => {
    setAiResults((prev) =>
      prev.map((r) => (r.id === cardId ? { ...r, collapsed: !r.collapsed } : r)),
    );
  }, []);

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
        isSelecting={isSelecting}
        onOpenFile={handleOpenFile}
        onPrevPage={prevPage}
        onNextPage={nextPage}
        onGoToPage={goToPage}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onToggleSelectionMode={handleToggleSelectionMode}
      />

      <div className="flex-1 flex overflow-hidden relative">
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
          hasSelection={!!selectedArea}
          activeTaskType={activeTaskType}
          userInput={userInput}
          panelMode={panelMode}
          onFollowUp={handleFollowUp}
          onClearCard={handleClearCard}
          onToggleCollapse={handleToggleCollapse}
          onAIRequest={handleAIRequest}
          onTaskTypeChange={setActiveTaskType}
          onUserInputChange={setUserInput}
          onPanelModeChange={setPanelMode}
        />
      </div>
    </div>
  );
}

import { useState, useRef, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { usePDF } from '@/hooks/usePDF';
import { translateSelection, type TaskType, type ConversationMessage, type HistoryConversation, getBook, listHistoryConversations } from '@/services/api';
import Toolbar from './components/Toolbar';
import ThumbnailPanel from './components/ThumbnailPanel';
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
  imageBase64: string;
  messages: Message[];
  timestamp: number;
}

interface SelectedArea {
  x: number;
  y: number;
  width: number;
  height: number;
}

export default function ReaderPage() {
  const { pdf_id } = useParams<{ pdf_id: string }>();
  const navigate = useNavigate();
  const {
    pdfDoc,
    numPages,
    currentPage,
    scale,
    isLoading,
    error: pdfError,
    fileName,
    loadPDF,
    setFileName,
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
  const [historyConversations, setHistoryConversations] = useState<HistoryConversation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeCardIdRef = useRef<number | null>(null);
  const historyRef = useRef<HistoryConversation[]>([]);

  // Keep ref in sync with history state for async callbacks
  useEffect(() => {
    historyRef.current = historyConversations;
  }, [historyConversations]);

  // Load book info from URL param
  useEffect(() => {
    if (pdf_id) {
      getBook(pdf_id).then((book) => {
        if (book) {
          setFileName(book.file_name);
        }
      });
    }
  }, [pdf_id, setFileName]);

  // Load history conversations for this book
  useEffect(() => {
    if (pdf_id) {
      setHistoryLoading(true);
      listHistoryConversations(pdf_id)
        .then((data) => {
          setHistoryConversations(data);
        })
        .catch(() => {
          setHistoryConversations([]);
        })
        .finally(() => {
          setHistoryLoading(false);
        });
    }
  }, [pdf_id]);

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

  const captureImage = useCallback(async () => {
    if (!selectedArea || !pdfDoc) return null;
    const page = await pdfDoc.getPage(currentPage);
    const captureScale = 2.0;
    const captureViewport = page.getViewport({ scale: captureScale });

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

    return offCanvas.toDataURL('image/png');
  }, [selectedArea, pdfDoc, currentPage]);

  const handleAIRequest = useCallback(
    async (taskType: TaskType, inputText?: string) => {
      if (!selectedArea || !pdfDoc) return;

      setIsAIWorking(true);
      setAiError(null);

      try {
        const imageBase64 = await captureImage();
        if (!imageBase64) throw new Error('Failed to capture image');

        const cardId = Date.now();
        activeCardIdRef.current = cardId;

        const initialMessages: Message[] = [];
        if (inputText && inputText.trim().length > 0) {
          initialMessages.push({
            id: cardId + 1,
            role: 'user',
            text: inputText.trim(),
            timestamp: Date.now(),
          });
        }

        setAiResults((prev) => [
          {
            id: cardId,
            type: taskType,
            imageBase64,
            messages: [...initialMessages],
            timestamp: Date.now(),
          },
          ...prev,
        ]);

        const result = await translateSelection(imageBase64, 'zh-CN', taskType, inputText);

        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const card = updated[idx];
          updated[idx] = {
            ...card,
            messages: [
              ...card.messages,
              {
                id: cardId + 2,
                role: 'ai',
                text: result.translated_text,
                timestamp: Date.now(),
              },
            ],
          };
          return updated;
        });
        activeCardIdRef.current = null;
      } catch (err: any) {
        setAiError(err.message || 'AI request failed. Please try again.');
        if (activeCardIdRef.current) {
          const failedCardId = activeCardIdRef.current;
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === failedCardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            const card = updated[idx];
            updated[idx] = {
              ...card,
              messages: [
                ...card.messages,
                {
                  id: failedCardId + 2,
                  role: 'ai',
                  text: 'Request failed',
                  timestamp: Date.now(),
                  isError: true,
                  errorText: err.message || 'AI request failed. Please try again.',
                },
              ],
            };
            return updated;
          });
        }
        activeCardIdRef.current = null;
      } finally {
        setIsAIWorking(false);
      }
    },
    [selectedArea, pdfDoc, captureImage],
  );

  const handleFollowUp = useCallback(
    async (cardId: number, text: string) => {
      if (!text.trim()) return;

      const now = Date.now();
      const userMsgId = now;
      const aiLoadingId = now + 1;

      setAiResults((prev) => {
        const idx = prev.findIndex((r) => r.id === cardId);
        if (idx === -1) return prev;
        const updated = [...prev];
        const card = updated[idx];
        updated[idx] = {
          ...card,
          messages: [
            ...card.messages,
            { id: userMsgId, role: 'user', text: text.trim(), timestamp: now },
            { id: aiLoadingId, role: 'ai', text: '', timestamp: now, isLoading: true },
          ],
        };
        return updated;
      });

      try {
        const card = aiResults.find((r) => r.id === cardId);
        if (!card) return;

        const conversationHistory: ConversationMessage[] = card.messages
          .filter((m) => !m.isLoading && !m.isError)
          .map((m) => ({
            role: m.role === 'user' ? 'user' : 'assistant',
            content: m.text,
          }));

        const result = await translateSelection(
          card.imageBase64,
          'zh-CN',
          card.type,
          text.trim(),
          conversationHistory,
        );

        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const card = updated[idx];
          const filtered = card.messages.filter((m) => m.id !== aiLoadingId);
          updated[idx] = {
            ...card,
            messages: [
              ...filtered,
              {
                id: aiLoadingId + 1,
                role: 'ai',
                text: result.translated_text,
                timestamp: Date.now(),
              },
            ],
          };
          return updated;
        });
      } catch (err: any) {
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const card = updated[idx];
          const filtered = card.messages.filter((m) => m.id !== aiLoadingId);
          updated[idx] = {
            ...card,
            messages: [
              ...filtered,
              {
                id: aiLoadingId + 1,
                role: 'ai',
                text: 'Request failed',
                timestamp: Date.now(),
                isError: true,
                errorText: err.message || 'AI request failed. Please try again.',
              },
            ],
          };
          return updated;
        });
      }
    },
    [aiResults],
  );

  const handleClearCard = useCallback((cardId: number) => {
    setAiResults((prev) => prev.filter((r) => r.id !== cardId));
  }, []);

  const handleHistoryFollowUp = useCallback(
    async (historyId: number, text: string) => {
      if (!text.trim()) return;

      const now = Date.now();
      const userMsgId = now;
      const aiLoadingId = now + 1;

      // Add user message + loading indicator
      setHistoryConversations((prev) => {
        const idx = prev.findIndex((h) => h.id === historyId);
        if (idx === -1) return prev;
        const updated = [...prev];
        const item = updated[idx];
        updated[idx] = {
          ...item,
          messages: [
            ...item.messages,
            { id: userMsgId, role: 'user', text: text.trim(), timestamp: now },
            { id: aiLoadingId, role: 'ai', text: '', timestamp: now, isLoading: true },
          ],
        };
        return updated;
      });

      try {
        const item = historyRef.current.find((h) => h.id === historyId);
        if (!item) return;

        const conversationHistory: ConversationMessage[] = item.messages
          .filter((m) => !m.isLoading && !m.isError)
          .map((m) => ({
            role: m.role === 'user' ? 'user' : 'assistant',
            content: m.text,
          }));

        const result = await translateSelection(
          item.thumbnail,
          'zh-CN',
          item.type,
          text.trim(),
          conversationHistory,
        );

        setHistoryConversations((prev) => {
          const idx = prev.findIndex((h) => h.id === historyId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const item = updated[idx];
          const filtered = item.messages.filter((m) => m.id !== aiLoadingId);
          updated[idx] = {
            ...item,
            messages: [
              ...filtered,
              {
                id: aiLoadingId + 1,
                role: 'ai',
                text: result.translated_text,
                timestamp: Date.now(),
              },
            ],
          };
          return updated;
        });
      } catch (err: any) {
        setHistoryConversations((prev) => {
          const idx = prev.findIndex((h) => h.id === historyId);
          if (idx === -1) return prev;
          const updated = [...prev];
          const item = updated[idx];
          const filtered = item.messages.filter((m) => m.id !== aiLoadingId);
          updated[idx] = {
            ...item,
            messages: [
              ...filtered,
              {
                id: aiLoadingId + 1,
                role: 'ai',
                text: 'Request failed',
                timestamp: Date.now(),
                isError: true,
                errorText: err.message || 'AI request failed. Please try again.',
              },
            ],
          };
          return updated;
        });
      }
    },
    [],
  );

  const displayName = fileName ? fileName.replace(/\.pdf$/i, '') : '';

  return (
    <div className="h-screen flex flex-col bg-stone-50">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,application/pdf"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Breadcrumb bar */}
      <div className="flex items-center gap-2 px-5 py-2 bg-white border-b border-stone-100">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-1 text-sm text-stone-500 hover:text-stone-700 hover:underline transition-colors cursor-pointer"
        >
          <i className="ri-arrow-left-line text-xs"></i>
          我的书架
        </button>
        <span className="text-stone-300 text-xs">›</span>
        <span className="text-sm text-stone-700 truncate max-w-[300px]" title={displayName}>
          {displayName || '未命名'}
        </span>
      </div>

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
        <ThumbnailPanel
          pdfDoc={pdfDoc}
          numPages={numPages}
          currentPage={currentPage}
          onPageClick={goToPage}
          isLoading={isLoading}
        />
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
          historyConversations={historyConversations}
          historyLoading={historyLoading}
          isAIWorking={isAIWorking}
          error={aiError}
          hasSelection={!!selectedArea}
          activeTaskType={activeTaskType}
          userInput={userInput}
          panelMode={panelMode}
          onFollowUp={handleFollowUp}
          onClearCard={handleClearCard}
          onAIRequest={handleAIRequest}
          onTaskTypeChange={setActiveTaskType}
          onUserInputChange={setUserInput}
          onPanelModeChange={setPanelMode}
          onHistoryFollowUp={handleHistoryFollowUp}
        />
      </div>
    </div>
  );
}
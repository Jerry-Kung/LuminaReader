import { useState, useRef, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { usePDF } from '@/hooks/usePDF';
import { usePdfReadingPosition } from '@/hooks/usePdfReadingPosition';
import {
  runTask,
  runFollowUp,
  clearSession,
  fetchLibrary,
  getPdfRawUrl,
  listConversations,
  listMessages,
  TranslateApiError,
  type TaskType,
  type ConversationSummary,
} from '@/services/api';
import Toolbar from './components/Toolbar';
import PDFViewer from './components/PDFViewer';
import AIAssistantPanel from './components/AIAssistantPanel';
import ThumbnailPanel from './components/ThumbnailPanel';

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

export interface HistoryEntry {
  conversationId: string;
  taskType: TaskType;
  summary: string;
  lastUsedAt: number;
  loaded: boolean;
  loading: boolean;
  loadError?: string;
  messages: Message[];
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
  if (err instanceof TranslateApiError) return `[${err.code}] ${err.message}`;
  if (err instanceof Error) return err.message;
  return 'AI request failed. Please try again.';
}

let msgSeq = 1;
function nextMsgId(): number {
  return Date.now() * 1000 + (msgSeq++ % 1000);
}

function summaryFromConversation(c: ConversationSummary): string {
  const candidate = c.first_assistant_summary?.trim();
  if (candidate) return candidate;
  return `第 ${c.selection?.page ?? '?'} 页选区`;
}

function summaryFromMessages(messages: Message[], fallback: string): string {
  const firstAi = messages.find((m) => m.role === 'ai' && !m.isLoading && !m.isError);
  const candidate = firstAi?.text?.trim();
  if (candidate) return candidate.slice(0, 200);
  return fallback;
}

export default function ReaderPage() {
  const { pdf_id: pdfId } = useParams<{ pdf_id: string }>();
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
    loadPDFFromUrl,
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
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // F9: 从 library 拿到的上次阅读位置 + 待跳标记。
  // 用 state 而非 ref：library 是异步的，PDF raw 可能命中浏览器缓存先 ready，
  // 必须靠 state 的 re-render 让 restore effect 在 library 完成后再次跑一遍。
  const [pendingRestorePage, setPendingRestorePage] = useState<number | null>(null);
  const [restoreAppliedForPdfId, setRestoreAppliedForPdfId] = useState<string | undefined>(undefined);

  // F1: 缩略图栏折叠状态。D2 默认展开；R-V104-5 窄屏（< 1280px）首次进入自动折叠。
  // 用户手动操作后不再被窗口变化覆盖（userOverride）。
  const [thumbnailCollapsed, setThumbnailCollapsed] = useState<boolean>(
    () => typeof window !== 'undefined' && window.innerWidth < 1280,
  );
  const thumbUserOverrideRef = useRef<boolean>(false);

  useEffect(() => {
    const handler = () => {
      if (thumbUserOverrideRef.current) return;
      setThumbnailCollapsed(window.innerWidth < 1280);
    };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  const handleToggleThumbnail = useCallback(() => {
    thumbUserOverrideRef.current = true;
    setThumbnailCollapsed((c) => !c);
  }, []);

  usePdfReadingPosition(pdfId, currentPage, restoreAppliedForPdfId === pdfId);

  // Load PDF bytes from backend when pdfId changes.
  useEffect(() => {
    if (!pdfId) return;
    loadPDFFromUrl(getPdfRawUrl(pdfId));
  }, [pdfId, loadPDFFromUrl]);

  // Resolve display name from library list (single-shot — the library endpoint is the source of truth for names).
  // V1.0.4 F9: also cache last_read_page for restore-on-open.
  // pendingRestorePage 语义：null = library 尚未返回；number（含 1）= 已返回，restore 可推进。
  // 即便值为 1，也必须显式 setPendingRestorePage(1)，否则 restoreAppliedForPdfId 不会被设，
  // 导致 hook 永久 disabled，用户翻页将无法写入 DB（新书首次阅读场景）。
  useEffect(() => {
    if (!pdfId) return;
    setPendingRestorePage(null);
    setRestoreAppliedForPdfId(undefined);
    let cancelled = false;
    fetchLibrary().then((items) => {
      if (cancelled) return;
      const match = items.find((item) => item.pdf_id === pdfId);
      if (match) {
        setFileName(match.primary_pdf_filename || match.name);
        const stored = match.last_read_page;
        setPendingRestorePage(
          Number.isInteger(stored) && stored >= 1 ? stored : 1,
        );
      } else {
        // PDF 不在 library 中（可能是上传后未刷新等边缘场景）：放弃 restore，但仍开闸允许写
        setPendingRestorePage(1);
      }
    }).catch(() => {
      if (!cancelled) setPendingRestorePage(1); // 网络失败也开闸，避免 hook 永久 disabled
    });
    return () => { cancelled = true; };
  }, [pdfId, setFileName]);

  // F9: restore last_read_page once BOTH numPages ready AND pendingRestorePage resolved from library.
  // Clamp to [1, numPages]. Only run once per pdfId.
  useEffect(() => {
    if (!pdfId || numPages <= 0) return;
    if (restoreAppliedForPdfId === pdfId) return;
    if (pendingRestorePage === null) return; // library 尚未返回，等下一次 re-render
    if (pendingRestorePage > 1) {
      const clamped = Math.min(pendingRestorePage, numPages);
      if (clamped > 1) goToPage(clamped);
    }
    setRestoreAppliedForPdfId(pdfId);
  }, [pdfId, numPages, pendingRestorePage, restoreAppliedForPdfId, goToPage]);

  // Load history conversations for this PDF.
  useEffect(() => {
    if (!pdfId) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    let cancelled = false;
    listConversations(pdfId)
      .then((items) => {
        if (cancelled) return;
        const entries: HistoryEntry[] = items.map((c) => ({
          conversationId: c.conversation_id,
          taskType: c.task_type,
          summary: summaryFromConversation(c),
          lastUsedAt: c.last_used_at,
          loaded: false,
          loading: false,
          messages: [],
        }));
        // Newest first by last_used_at desc.
        entries.sort((a, b) => b.lastUsedAt - a.lastUsedAt);
        setHistory(entries);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => { cancelled = true; };
  }, [pdfId]);

  const handleBackToLibrary = useCallback(() => {
    navigate('/');
  }, [navigate]);

  const handleOpenFile = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  // Fallback path: drop a local PDF (kept for development; book uploads happen from bookshelf).
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
        }, { targetLang: 'zh-CN', userQuestion: trimmedInput, pdfId });

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
    [selectedArea, pdfDoc, captureImage, pdfId],
  );

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

  const handleClearCard = useCallback(
    async (cardId: number) => {
      const card = aiResults.find((r) => r.id === cardId);
      if (card?.sessionId) {
        try {
          await clearSession(card.sessionId);
        } catch {
          // Session release failed (network/server); still clear the local card.
        }
        // If this card was promoted from history, drop it from the history list too.
        setHistory((prev) => prev.filter((h) => h.conversationId !== card.sessionId));
        if (expandedHistoryId === card.sessionId) setExpandedHistoryId(null);
      }
      setAiResults((prev) => prev.filter((r) => r.id !== cardId));
    },
    [aiResults, expandedHistoryId],
  );

  const handleToggleCollapse = useCallback((cardId: number) => {
    setAiResults((prev) =>
      prev.map((r) => (r.id === cardId ? { ...r, collapsed: !r.collapsed } : r)),
    );
  }, []);

  // Lazy-load full messages for a history conversation on first expand.
  const ensureHistoryLoaded = useCallback(
    async (conversationId: string) => {
      const target = history.find((h) => h.conversationId === conversationId);
      if (!target || target.loaded || target.loading) return;

      setHistory((prev) =>
        prev.map((h) => (h.conversationId === conversationId ? { ...h, loading: true, loadError: undefined } : h)),
      );

      try {
        const detail = await listMessages(conversationId);
        const messages: Message[] = detail.messages.map((m) => ({
          id: nextMsgId(),
          role: m.role === 'user' ? 'user' : 'ai',
          text: m.content,
          timestamp: (m.created_at || 0) * 1000,
        }));
        setHistory((prev) =>
          prev.map((h) =>
            h.conversationId === conversationId
              ? {
                  ...h,
                  loaded: true,
                  loading: false,
                  messages,
                  summary: summaryFromMessages(messages, h.summary),
                }
              : h,
          ),
        );
      } catch (err) {
        const msg = formatError(err);
        setHistory((prev) =>
          prev.map((h) =>
            h.conversationId === conversationId ? { ...h, loading: false, loadError: msg } : h,
          ),
        );
      }
    },
    [history],
  );

  const handleToggleHistory = useCallback(
    (conversationId: string) => {
      setExpandedHistoryId((prev) => (prev === conversationId ? null : conversationId));
      ensureHistoryLoaded(conversationId);
    },
    [ensureHistoryLoaded],
  );

  const handleDeleteHistory = useCallback(
    async (conversationId: string) => {
      const entry = history.find((h) => h.conversationId === conversationId);
      const label = entry?.summary?.trim() ? entry.summary.slice(0, 40) : '该历史对话';
      const ok = window.confirm(`确定删除「${label}」？此操作不可撤销。`);
      if (!ok) return;
      try {
        await clearSession(conversationId);
      } catch {
        // Session release failed (network/server); proceed with local cleanup so UI does not feel stuck.
      }
      setHistory((prev) => prev.filter((h) => h.conversationId !== conversationId));
      setExpandedHistoryId((prev) => (prev === conversationId ? null : prev));
      setAiResults((prev) => prev.filter((r) => r.sessionId !== conversationId));
    },
    [history],
  );

  // Continue a history conversation: append user/loading turns locally, then runFollowUp(conversation_id).
  const handleHistoryFollowUp = useCallback(
    async (conversationId: string, text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const entry = history.find((h) => h.conversationId === conversationId);
      if (!entry) return;

      const loadingId = nextMsgId();

      setHistory((prev) =>
        prev.map((h) =>
          h.conversationId === conversationId
            ? {
                ...h,
                messages: [
                  ...h.messages,
                  { id: nextMsgId(), role: 'user', text: trimmed, timestamp: Date.now() },
                  { id: loadingId, role: 'ai', text: '', timestamp: Date.now(), isLoading: true },
                ],
              }
            : h,
        ),
      );

      try {
        const result = await runFollowUp(entry.taskType, conversationId, trimmed, { targetLang: 'zh-CN' });
        setHistory((prev) =>
          prev.map((h) => {
            if (h.conversationId !== conversationId) return h;
            const filtered = h.messages.filter((m) => m.id !== loadingId);
            return {
              ...h,
              lastUsedAt: Math.floor(Date.now() / 1000),
              messages: [
                ...filtered,
                { id: nextMsgId(), role: 'ai', text: result.text, timestamp: Date.now() },
              ],
            };
          }),
        );
      } catch (err) {
        const msg = formatError(err);
        setHistory((prev) =>
          prev.map((h) => {
            if (h.conversationId !== conversationId) return h;
            const filtered = h.messages.filter((m) => m.id !== loadingId);
            return {
              ...h,
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
          }),
        );
      }
    },
    [history],
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

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 px-5 py-2 bg-white border-b border-stone-100">
        <button
          onClick={handleBackToLibrary}
          className="flex items-center gap-1 text-sm text-stone-500 hover:text-stone-700 hover:underline transition-colors cursor-pointer"
        >
          <i className="ri-arrow-left-line text-xs"></i>
          我的书架
        </button>
        <span className="text-stone-300 text-xs">›</span>
        <span className="text-sm text-stone-700 truncate max-w-[420px]" title={displayName}>
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
          collapsed={thumbnailCollapsed}
          onToggleCollapsed={handleToggleThumbnail}
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
          history={history}
          historyLoading={historyLoading}
          expandedHistoryId={expandedHistoryId}
          onToggleHistory={handleToggleHistory}
          onHistoryFollowUp={handleHistoryFollowUp}
          onDeleteHistory={handleDeleteHistory}
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

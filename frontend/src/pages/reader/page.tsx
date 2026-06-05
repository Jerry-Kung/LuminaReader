import { useState, useRef, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { usePDF } from '@/hooks/usePDF';
import { usePdfReadingPosition } from '@/hooks/usePdfReadingPosition';
import {
  runTaskStream,
  runFollowUpStream,
  clearSession,
  fetchLibrary,
  getPdfRawUrl,
  listConversations,
  listMessages,
  TranslateApiError,
  classifyApiError,
  errorMessageFor,
  type TaskType,
  type ErrorCategory,
  type ConversationSummary,
  type RunStreamHandle,
  type RunStreamCallbacks,
  type StreamMeta,
} from '@/services/api';
import Toolbar from './components/Toolbar';
import PDFViewer from './components/PDFViewer';
import AIAssistantPanel, { type ChipPluginType, type ChipsState } from './components/AIAssistantPanel';
import ThumbnailPanel from './components/ThumbnailPanel';

type RetryPayload =
  | {
      kind: 'first_turn';
      cardId: number;
      taskType: TaskType;
      plugins: ChipPluginType[];
      capture: CaptureResult;
      userInput?: string;
      pdfId?: string;
    }
  | {
      kind: 'follow_up';
      cardId: number;
      taskType: TaskType;
      plugins: ChipPluginType[];
      sessionId: string;
      userInput: string;
    }
  | {
      kind: 'history_follow_up';
      conversationId: string;
      taskType: TaskType;
      plugins: ChipPluginType[];
      userInput: string;
    };

export interface Message {
  id: number;
  role: 'user' | 'ai';
  text: string;
  timestamp: number;
  isLoading?: boolean;
  isStreaming?: boolean;
  isError?: boolean;
  errorText?: string;
  errorCategory?: ErrorCategory;
  retry?: RetryPayload;
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

function errorMessageFrom(err: unknown): { category: ErrorCategory; display: string } {
  const category = classifyApiError(err);
  return { category, display: errorMessageFor(category) };
}

function buildErrorMessage(messageId: number, err: unknown, retry?: RetryPayload): Message {
  const { category, display } = errorMessageFrom(err);
  // STREAM 错误帧 retriable=false 时，不塞 retry，UI 不展示重试按钮
  const allowRetry = !(err instanceof TranslateApiError) || err.retriable !== false;
  return {
    id: messageId,
    role: 'ai',
    text: '',
    timestamp: Date.now(),
    isError: true,
    errorCategory: category,
    errorText: display,
    retry: allowRetry ? retry : undefined,
  };
}

function loadingMessage(messageId: number): Message {
  return {
    id: messageId,
    role: 'ai',
    text: '',
    timestamp: Date.now(),
    isLoading: true,
  };
}

let msgSeq = 1;
function nextMsgId(): number {
  return Date.now() * 1000 + (msgSeq++ % 1000);
}

// 把卡片/历史保存的单一 TaskType 还原为 plugins 数组：
// 'chat' → []（自由 Chat 模式）；其它三类 → [type]。
// 追问轮后端允许跨插件，但前端默认沿用本卡的 type，无 UI 让用户改。
function taskTypeToPlugins(t: TaskType): ChipPluginType[] {
  if (t === 'chat') return [];
  return [t];
}

interface TextDeltaCommitter {
  push: (delta: string) => void;
  flushNow: () => void;
  reset: () => void;
}

function createTextDeltaCommitter(
  flushFn: (appended: string) => void,
  intervalMs = 50,
): TextDeltaCommitter {
  let buf = '';
  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = () => {
    if (!buf) return;
    const payload = buf;
    buf = '';
    flushFn(payload);
  };
  return {
    push(delta: string) {
      buf += delta;
      if (timer === null) {
        timer = setTimeout(() => {
          timer = null;
          flush();
        }, intervalMs);
      }
    },
    flushNow() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      flush();
    },
    reset() {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      buf = '';
    },
  };
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
  const [activeTaskTypes, setActiveTaskTypes] = useState<ChipPluginType[]>([]);
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
  const retryInFlightRef = useRef(false);
  // V1.1.0 F1: 流式 in-flight handles。卡内 stream key=cardId；history follow-up key=conversationId。
  const cardStreamsRef = useRef<Map<number, RunStreamHandle>>(new Map());
  const historyStreamsRef = useRef<Map<string, RunStreamHandle>>(new Map());

  // Unmount cleanup: abort 所有 in-flight 流，避免回调对已卸载组件 setState。
  useEffect(() => {
    return () => {
      cardStreamsRef.current.forEach((h) => h.abort());
      cardStreamsRef.current.clear();
      historyStreamsRef.current.forEach((h) => h.abort());
      historyStreamsRef.current.clear();
    };
  }, []);

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

  // pdfId 切换：abort 所有 in-flight 流（避免回调对已重置的 aiResults/history 写入）。
  // 注意：保留 effect 顺序——必须在依赖 pdfId 的其他 setAiResults/setHistory effect 之前。
  useEffect(() => {
    cardStreamsRef.current.forEach((h) => h.abort());
    cardStreamsRef.current.clear();
    historyStreamsRef.current.forEach((h) => h.abort());
    historyStreamsRef.current.clear();
  }, [pdfId]);

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

  const handleTaskTypeToggle = useCallback((type: ChipPluginType) => {
    setActiveTaskTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }, []);

  // chipsState：首轮发起前，前端无法本地求字数（OCR 文本由首轮 extract 任务产出），
  // 因此 dictionary 在 UI 上默认 disabled + tooltip，仅作引导；用户即便绕过前端发请求，
  // 后端 applicable_when（max=3）会兜底返回 400 INVALID_REQUEST。
  const hasSelection = !!selectedArea;
  const chipsState: ChipsState = {
    translate: { state: hasSelection ? 'available' : 'disabled' },
    explain: { state: hasSelection ? 'available' : 'disabled' },
    dictionary: { state: 'disabled', reason: '仅支持 3 个词以内的文字选区' },
  };

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
    async (taskTypes: ChipPluginType[], inputText?: string) => {
      if (!selectedArea || !pdfDoc) return;
      const trimmedInput = inputText?.trim();
      // V1.1.1：空 chip 列表时需有用户输入才能成立（自由 Chat 模式）
      if (taskTypes.length === 0 && !trimmedInput) return;

      setIsAIWorking(true);
      setAiError(null);

      const cardId = nextMsgId();
      const loadingId = nextMsgId();

      let capture: CaptureResult;
      try {
        const captured = await captureImage();
        if (!captured) throw new Error('Failed to capture image');
        capture = captured;
      } catch (err) {
        const { display } = errorMessageFrom(err);
        setAiError(display);
        setIsAIWorking(false);
        return;
      }

      const initialMessages: Message[] = [];
      if (trimmedInput) {
        initialMessages.push({
          id: nextMsgId(),
          role: 'user',
          text: trimmedInput,
          timestamp: Date.now(),
        });
      }
      initialMessages.push(loadingMessage(loadingId));

      // 卡片头部徽章用 plugins[0]；plugins 为空（自由 Chat）走 'chat' 徽章
      const cardTaskType: TaskType = taskTypes[0] ?? 'chat';

      setAiResults((prev) => [
        ...prev.map((r) => (r.collapsed ? r : { ...r, collapsed: true })),
        {
          id: cardId,
          type: cardTaskType,
          sessionId: '',
          imageBase64: capture.dataUrl,
          messages: initialMessages,
          timestamp: Date.now(),
          collapsed: false,
        },
      ]);

      const retryPayload: RetryPayload = {
        kind: 'first_turn',
        cardId,
        taskType: cardTaskType,
        plugins: [...taskTypes],
        capture,
        userInput: trimmedInput,
        pdfId,
      };

      const committer = createTextDeltaCommitter((appended) => {
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            messages: updated[idx].messages.map((m) =>
              m.id === loadingId
                ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                : m,
            ),
          };
          return updated;
        });
      });

      const finalize = () => {
        committer.reset();
        cardStreamsRef.current.delete(cardId);
        setIsAIWorking(false);
      };

      const callbacks: RunStreamCallbacks = {
        onMeta: (meta: StreamMeta) => {
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              sessionId: meta.session_id,
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId
                  ? { ...m, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
            return updated;
          });
        },
        onTextDelta: (delta) => committer.push(delta),
        onUsage: () => { /* 本任务不在 UI 持久化 usage；后端落 DB 即可 */ },
        onDone: () => {
          committer.flushNow();
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId ? { ...m, isStreaming: false } : m,
              ),
            };
            return updated;
          });
          finalize();
        },
        onError: (err, { partialTextKept }) => {
          committer.flushNow();
          const { display } = errorMessageFrom(err);
          setAiError(display);
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            const messages = updated[idx].messages;
            const loadingIdx = messages.findIndex((m) => m.id === loadingId);
            if (loadingIdx === -1) return prev;
            const loadingMsg = messages[loadingIdx];
            const hasPartial = partialTextKept && (loadingMsg.text || '').length > 0;
            if (hasPartial) {
              // 把流式气泡定型为正常 ai 文本（保留 partial），后面追加独立 error 气泡
              const finalized: Message = {
                ...loadingMsg,
                isLoading: false,
                isStreaming: false,
              };
              const errorMsg = buildErrorMessage(nextMsgId(), err, retryPayload);
              updated[idx] = {
                ...updated[idx],
                messages: [
                  ...messages.slice(0, loadingIdx),
                  finalized,
                  errorMsg,
                  ...messages.slice(loadingIdx + 1),
                ],
              };
            } else {
              // 复用 loadingId 转 error
              updated[idx] = {
                ...updated[idx],
                messages: messages.map((m) =>
                  m.id === loadingId ? buildErrorMessage(loadingId, err, retryPayload) : m,
                ),
              };
            }
            return updated;
          });
          finalize();
        },
      };

      const handle = runTaskStream(
        taskTypes,
        capture.selection,
        { data: capture.base64, width: capture.width, height: capture.height },
        { targetLang: 'zh-CN', userInput: trimmedInput, pdfId },
        callbacks,
      );
      cardStreamsRef.current.set(cardId, handle);
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
      const sessionId = card.sessionId;
      const taskType = card.type;

      setAiResults((prev) => {
        const idx = prev.findIndex((r) => r.id === cardId);
        if (idx === -1) return prev;
        const updated = [...prev];
        updated[idx] = {
          ...updated[idx],
          messages: [
            ...updated[idx].messages,
            { id: nextMsgId(), role: 'user', text: trimmed, timestamp: Date.now() },
            loadingMessage(loadingId),
          ],
        };
        return updated;
      });

      const retryPayload: RetryPayload = {
        kind: 'follow_up',
        cardId,
        taskType,
        plugins: taskTypeToPlugins(taskType),
        sessionId,
        userInput: trimmed,
      };

      const committer = createTextDeltaCommitter((appended) => {
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            messages: updated[idx].messages.map((m) =>
              m.id === loadingId
                ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                : m,
            ),
          };
          return updated;
        });
      });

      const finalize = () => {
        committer.reset();
        cardStreamsRef.current.delete(cardId);
      };

      const callbacks: RunStreamCallbacks = {
        onMeta: () => {
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId
                  ? { ...m, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
            return updated;
          });
        },
        onTextDelta: (delta) => committer.push(delta),
        onUsage: () => {},
        onDone: () => {
          committer.flushNow();
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId ? { ...m, isStreaming: false } : m,
              ),
            };
            return updated;
          });
          finalize();
        },
        onError: (err, { partialTextKept }) => {
          committer.flushNow();
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            const messages = updated[idx].messages;
            const loadingIdx = messages.findIndex((m) => m.id === loadingId);
            if (loadingIdx === -1) return prev;
            const loadingMsg = messages[loadingIdx];
            const hasPartial = partialTextKept && (loadingMsg.text || '').length > 0;
            if (hasPartial) {
              const finalized: Message = { ...loadingMsg, isLoading: false, isStreaming: false };
              const errorMsg = buildErrorMessage(nextMsgId(), err, retryPayload);
              updated[idx] = {
                ...updated[idx],
                messages: [
                  ...messages.slice(0, loadingIdx),
                  finalized,
                  errorMsg,
                  ...messages.slice(loadingIdx + 1),
                ],
              };
            } else {
              updated[idx] = {
                ...updated[idx],
                messages: messages.map((m) =>
                  m.id === loadingId ? buildErrorMessage(loadingId, err, retryPayload) : m,
                ),
              };
            }
            return updated;
          });
          finalize();
        },
      };

      const handle = runFollowUpStream(taskTypeToPlugins(taskType), sessionId, trimmed, { targetLang: 'zh-CN' }, callbacks);
      cardStreamsRef.current.set(cardId, handle);
    },
    [aiResults],
  );

  const handleClearCard = useCallback(
    async (cardId: number) => {
      // 先 abort in-flight 流（如果正在流），避免回调对已删除卡片 setState
      const inflight = cardStreamsRef.current.get(cardId);
      if (inflight) {
        inflight.abort();
        cardStreamsRef.current.delete(cardId);
        setIsAIWorking(false);
      }
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
      // 若该历史正在流式追问，先 abort
      const inflight = historyStreamsRef.current.get(conversationId);
      if (inflight) {
        inflight.abort();
        historyStreamsRef.current.delete(conversationId);
      }
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

  // Continue a history conversation: append user/loading turns locally, then stream follow-up.
  const handleHistoryFollowUp = useCallback(
    async (conversationId: string, text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const entry = history.find((h) => h.conversationId === conversationId);
      if (!entry) return;

      const loadingId = nextMsgId();
      const taskType = entry.taskType;

      setHistory((prev) =>
        prev.map((h) =>
          h.conversationId === conversationId
            ? {
                ...h,
                messages: [
                  ...h.messages,
                  { id: nextMsgId(), role: 'user', text: trimmed, timestamp: Date.now() },
                  loadingMessage(loadingId),
                ],
              }
            : h,
        ),
      );

      const retryPayload: RetryPayload = {
        kind: 'history_follow_up',
        conversationId,
        taskType,
        plugins: taskTypeToPlugins(taskType),
        userInput: trimmed,
      };

      const committer = createTextDeltaCommitter((appended) => {
        setHistory((prev) =>
          prev.map((h) => {
            if (h.conversationId !== conversationId) return h;
            return {
              ...h,
              messages: h.messages.map((m) =>
                m.id === loadingId
                  ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
          }),
        );
      });

      const finalize = () => {
        committer.reset();
        historyStreamsRef.current.delete(conversationId);
      };

      const callbacks: RunStreamCallbacks = {
        onMeta: () => {
          setHistory((prev) =>
            prev.map((h) => {
              if (h.conversationId !== conversationId) return h;
              return {
                ...h,
                messages: h.messages.map((m) =>
                  m.id === loadingId
                    ? { ...m, isLoading: false, isStreaming: true }
                    : m,
                ),
              };
            }),
          );
        },
        onTextDelta: (delta) => committer.push(delta),
        onUsage: () => {},
        onDone: () => {
          committer.flushNow();
          setHistory((prev) =>
            prev.map((h) => {
              if (h.conversationId !== conversationId) return h;
              return {
                ...h,
                lastUsedAt: Math.floor(Date.now() / 1000),
                messages: h.messages.map((m) =>
                  m.id === loadingId ? { ...m, isStreaming: false } : m,
                ),
              };
            }),
          );
          finalize();
        },
        onError: (err, { partialTextKept }) => {
          committer.flushNow();
          setHistory((prev) =>
            prev.map((h) => {
              if (h.conversationId !== conversationId) return h;
              const loadingIdx = h.messages.findIndex((m) => m.id === loadingId);
              if (loadingIdx === -1) return h;
              const loadingMsg = h.messages[loadingIdx];
              const hasPartial = partialTextKept && (loadingMsg.text || '').length > 0;
              if (hasPartial) {
                const finalized: Message = { ...loadingMsg, isLoading: false, isStreaming: false };
                const errorMsg = buildErrorMessage(nextMsgId(), err, retryPayload);
                return {
                  ...h,
                  messages: [
                    ...h.messages.slice(0, loadingIdx),
                    finalized,
                    errorMsg,
                    ...h.messages.slice(loadingIdx + 1),
                  ],
                };
              }
              return {
                ...h,
                messages: h.messages.map((m) =>
                  m.id === loadingId ? buildErrorMessage(loadingId, err, retryPayload) : m,
                ),
              };
            }),
          );
          finalize();
        },
      };

      const handle = runFollowUpStream(taskTypeToPlugins(taskType), conversationId, trimmed, { targetLang: 'zh-CN' }, callbacks);
      historyStreamsRef.current.set(conversationId, handle);
    },
    [history],
  );

  const handleRetry = useCallback(
    async (msg: Message) => {
      if (!msg.retry || retryInFlightRef.current) return;
      retryInFlightRef.current = true;
      const r = msg.retry;
      const errorId = msg.id;
      const loadingId = nextMsgId();

      // helper: 把当前 message 列表中"error 前紧邻的非 user/loading/error 的 ai message"视为 partial 一并删除，
      // error 自身位置插入新 loading message。
      const replaceErrorWithLoading = (messages: Message[]): Message[] => {
        const errIdx = messages.findIndex((m) => m.id === errorId);
        if (errIdx === -1) return messages;
        // 检测前一条是不是 partial（role=ai 且无 isLoading/isError/isStreaming）
        const prev = errIdx > 0 ? messages[errIdx - 1] : null;
        const isPartial =
          prev &&
          prev.role === 'ai' &&
          !prev.isLoading &&
          !prev.isStreaming &&
          !prev.isError &&
          (prev.text || '').length > 0;
        if (isPartial) {
          return [
            ...messages.slice(0, errIdx - 1),
            loadingMessage(loadingId),
            ...messages.slice(errIdx + 1),
          ];
        }
        return messages.map((m) => (m.id === errorId ? loadingMessage(loadingId) : m));
      };

      if (r.kind === 'first_turn') {
        // 防御性：旧 in-flight 流 abort（极少触达，retryInFlight 已挡）
        cardStreamsRef.current.get(r.cardId)?.abort();
        cardStreamsRef.current.delete(r.cardId);

        setAiResults((prev) =>
          prev.map((card) =>
            card.id === r.cardId
              ? { ...card, messages: replaceErrorWithLoading(card.messages) }
              : card,
          ),
        );
        setAiError(null);
        setIsAIWorking(true);

        const committer = createTextDeltaCommitter((appended) => {
          setAiResults((prev) => {
            const idx = prev.findIndex((c) => c.id === r.cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId
                  ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
            return updated;
          });
        });

        const finalize = () => {
          committer.reset();
          cardStreamsRef.current.delete(r.cardId);
          setIsAIWorking(false);
          retryInFlightRef.current = false;
        };

        const callbacks: RunStreamCallbacks = {
          onMeta: (meta: StreamMeta) => {
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              updated[idx] = {
                ...updated[idx],
                sessionId: meta.session_id,
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, isLoading: false, isStreaming: true } : m,
                ),
              };
              return updated;
            });
          },
          onTextDelta: (delta) => committer.push(delta),
          onUsage: () => {},
          onDone: () => {
            committer.flushNow();
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              updated[idx] = {
                ...updated[idx],
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, isStreaming: false } : m,
                ),
              };
              return updated;
            });
            finalize();
          },
          onError: (err, { partialTextKept }) => {
            committer.flushNow();
            const { display } = errorMessageFrom(err);
            setAiError(display);
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              const messages = updated[idx].messages;
              const loadIdx = messages.findIndex((m) => m.id === loadingId);
              if (loadIdx === -1) return prev;
              const loadMsg = messages[loadIdx];
              const hasPartial = partialTextKept && (loadMsg.text || '').length > 0;
              if (hasPartial) {
                const finalized: Message = { ...loadMsg, isLoading: false, isStreaming: false };
                const errorMsg = buildErrorMessage(nextMsgId(), err, r);
                updated[idx] = {
                  ...updated[idx],
                  messages: [
                    ...messages.slice(0, loadIdx),
                    finalized,
                    errorMsg,
                    ...messages.slice(loadIdx + 1),
                  ],
                };
              } else {
                updated[idx] = {
                  ...updated[idx],
                  messages: messages.map((m) =>
                    m.id === loadingId ? buildErrorMessage(loadingId, err, r) : m,
                  ),
                };
              }
              return updated;
            });
            finalize();
          },
        };

        const handle = runTaskStream(
          r.plugins,
          r.capture.selection,
          { data: r.capture.base64, width: r.capture.width, height: r.capture.height },
          { targetLang: 'zh-CN', userInput: r.userInput, pdfId: r.pdfId },
          callbacks,
        );
        cardStreamsRef.current.set(r.cardId, handle);
      } else if (r.kind === 'follow_up') {
        cardStreamsRef.current.get(r.cardId)?.abort();
        cardStreamsRef.current.delete(r.cardId);

        setAiResults((prev) =>
          prev.map((card) =>
            card.id === r.cardId
              ? { ...card, messages: replaceErrorWithLoading(card.messages) }
              : card,
          ),
        );

        const committer = createTextDeltaCommitter((appended) => {
          setAiResults((prev) => {
            const idx = prev.findIndex((c) => c.id === r.cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId
                  ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
            return updated;
          });
        });

        const finalize = () => {
          committer.reset();
          cardStreamsRef.current.delete(r.cardId);
          retryInFlightRef.current = false;
        };

        const callbacks: RunStreamCallbacks = {
          onMeta: () => {
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              updated[idx] = {
                ...updated[idx],
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, isLoading: false, isStreaming: true } : m,
                ),
              };
              return updated;
            });
          },
          onTextDelta: (delta) => committer.push(delta),
          onUsage: () => {},
          onDone: () => {
            committer.flushNow();
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              updated[idx] = {
                ...updated[idx],
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, isStreaming: false } : m,
                ),
              };
              return updated;
            });
            finalize();
          },
          onError: (err, { partialTextKept }) => {
            committer.flushNow();
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              const messages = updated[idx].messages;
              const loadIdx = messages.findIndex((m) => m.id === loadingId);
              if (loadIdx === -1) return prev;
              const loadMsg = messages[loadIdx];
              const hasPartial = partialTextKept && (loadMsg.text || '').length > 0;
              if (hasPartial) {
                const finalized: Message = { ...loadMsg, isLoading: false, isStreaming: false };
                const errorMsg = buildErrorMessage(nextMsgId(), err, r);
                updated[idx] = {
                  ...updated[idx],
                  messages: [
                    ...messages.slice(0, loadIdx),
                    finalized,
                    errorMsg,
                    ...messages.slice(loadIdx + 1),
                  ],
                };
              } else {
                updated[idx] = {
                  ...updated[idx],
                  messages: messages.map((m) =>
                    m.id === loadingId ? buildErrorMessage(loadingId, err, r) : m,
                  ),
                };
              }
              return updated;
            });
            finalize();
          },
        };

        const handle = runFollowUpStream(
          r.plugins,
          r.sessionId,
          r.userInput,
          { targetLang: 'zh-CN' },
          callbacks,
        );
        cardStreamsRef.current.set(r.cardId, handle);
      } else {
        // history_follow_up
        historyStreamsRef.current.get(r.conversationId)?.abort();
        historyStreamsRef.current.delete(r.conversationId);

        setHistory((prev) =>
          prev.map((h) =>
            h.conversationId === r.conversationId
              ? { ...h, messages: replaceErrorWithLoading(h.messages) }
              : h,
          ),
        );

        const committer = createTextDeltaCommitter((appended) => {
          setHistory((prev) =>
            prev.map((h) => {
              if (h.conversationId !== r.conversationId) return h;
              return {
                ...h,
                messages: h.messages.map((m) =>
                  m.id === loadingId
                    ? { ...m, text: (m.text || '') + appended, isLoading: false, isStreaming: true }
                    : m,
                ),
              };
            }),
          );
        });

        const finalize = () => {
          committer.reset();
          historyStreamsRef.current.delete(r.conversationId);
          retryInFlightRef.current = false;
        };

        const callbacks: RunStreamCallbacks = {
          onMeta: () => {
            setHistory((prev) =>
              prev.map((h) => {
                if (h.conversationId !== r.conversationId) return h;
                return {
                  ...h,
                  messages: h.messages.map((m) =>
                    m.id === loadingId ? { ...m, isLoading: false, isStreaming: true } : m,
                  ),
                };
              }),
            );
          },
          onTextDelta: (delta) => committer.push(delta),
          onUsage: () => {},
          onDone: () => {
            committer.flushNow();
            setHistory((prev) =>
              prev.map((h) => {
                if (h.conversationId !== r.conversationId) return h;
                return {
                  ...h,
                  lastUsedAt: Math.floor(Date.now() / 1000),
                  messages: h.messages.map((m) =>
                    m.id === loadingId ? { ...m, isStreaming: false } : m,
                  ),
                };
              }),
            );
            finalize();
          },
          onError: (err, { partialTextKept }) => {
            committer.flushNow();
            setHistory((prev) =>
              prev.map((h) => {
                if (h.conversationId !== r.conversationId) return h;
                const loadIdx = h.messages.findIndex((m) => m.id === loadingId);
                if (loadIdx === -1) return h;
                const loadMsg = h.messages[loadIdx];
                const hasPartial = partialTextKept && (loadMsg.text || '').length > 0;
                if (hasPartial) {
                  const finalized: Message = { ...loadMsg, isLoading: false, isStreaming: false };
                  const errorMsg = buildErrorMessage(nextMsgId(), err, r);
                  return {
                    ...h,
                    messages: [
                      ...h.messages.slice(0, loadIdx),
                      finalized,
                      errorMsg,
                      ...h.messages.slice(loadIdx + 1),
                    ],
                  };
                }
                return {
                  ...h,
                  messages: h.messages.map((m) =>
                    m.id === loadingId ? buildErrorMessage(loadingId, err, r) : m,
                  ),
                };
              }),
            );
            finalize();
          },
        };

        const handle = runFollowUpStream(
          r.plugins,
          r.conversationId,
          r.userInput,
          { targetLang: 'zh-CN' },
          callbacks,
        );
        historyStreamsRef.current.set(r.conversationId, handle);
      }
    },
    [],
  );

  const handleDismissError = useCallback((msg: Message) => {
    if (!msg.retry) return;
    const r = msg.retry;
    if (r.kind === 'history_follow_up') {
      setHistory((prev) =>
        prev.map((h) =>
          h.conversationId === r.conversationId
            ? { ...h, messages: h.messages.filter((m) => m.id !== msg.id) }
            : h,
        ),
      );
    } else {
      setAiResults((prev) =>
        prev.map((card) =>
          card.id === r.cardId
            ? { ...card, messages: card.messages.filter((m) => m.id !== msg.id) }
            : card,
        ),
      );
    }
    setAiError(null);
  }, []);

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
        onOpenSettings={() => navigate('/settings', { state: { from: `/reader/${pdfId}` } })}
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
          activeTaskTypes={activeTaskTypes}
          userInput={userInput}
          panelMode={panelMode}
          chipsState={chipsState}
          onFollowUp={handleFollowUp}
          onClearCard={handleClearCard}
          onToggleCollapse={handleToggleCollapse}
          onAIRequest={handleAIRequest}
          onTaskTypeToggle={handleTaskTypeToggle}
          onUserInputChange={setUserInput}
          onPanelModeChange={setPanelMode}
          onRetry={handleRetry}
          onDismissError={handleDismissError}
        />
      </div>
    </div>
  );
}

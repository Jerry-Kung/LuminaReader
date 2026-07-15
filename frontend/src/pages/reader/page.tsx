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
  type FirstTurnSelection,
} from '@/services/api';
import Toolbar, { type CursorMode } from './components/Toolbar';
import PDFViewer, { type SelectedArea } from './components/PDFViewer';
import AIAssistantPanel, { type ChipPluginType, type ChipsState } from './components/AIAssistantPanel';
import ThumbnailPanel from './components/ThumbnailPanel';
import { useTextSelection } from './hooks/useTextSelection';

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
  // V1.1.2 screenshot-qa：首轮 OCR 折叠区文本（非首轮场景 undefined）
  ocrText?: string;
  // OCR 段已被 SSE extracted_text 事件以权威值覆盖（后续 delta 不应再追加）
  ocrAuthoritative?: boolean;
  ocrCollapsed?: boolean;
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

// V1.1.3：SelectedArea 类型来自 PDFViewer，多页 canvas 模式下含 page 字段（起点页 clamp）

// V1.1.4：首轮捕获结果 = 截图捕获 or 文字捕获
interface ImageCaptureResult {
  kind: 'image';
  dataUrl: string;
  base64: string;
  width: number;
  height: number;
  selection: { page: number; x: number; y: number; w: number; h: number; dpi: number };
}

interface TextCaptureResult {
  kind: 'text';
  // 用于卡片头部预览（没有截图所以传空 dataUrl，AIAssistantPanel 端按 kind 决定如何显示）
  dataUrl: '';
  text: string;
  pageStart: number;
  pageEnd: number;
  segments: Array<{ page: number; text: string; offset_start: number; offset_end: number }>;
  wordCount: number;
}

type CaptureResult = ImageCaptureResult | TextCaptureResult;

const READING_OFFSET_NOTICE_KEY = 'lumina:v1.1.3_offset_notice_shown';

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
// V1.1.2：'screenshot-qa' 是后端按 image 自动激活的内部插件，追问轮（无 image）
// 显式带它会让 LLM 仍被强制要求输出 <ocr>/<answer> 双标签 → 标签泄漏到 UI。
// 追问轮统一退化为 chat 模式，后端会用 session.extracted_text 作为上下文。
function taskTypeToPlugins(t: TaskType): ChipPluginType[] {
  if (t === 'chat' || t === 'screenshot-qa') return [];
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
    currentOffset,
    scale,
    isLoading,
    error: pdfError,
    fileName,
    pendingScrollTarget,
    loadPDF,
    loadPDFFromUrl,
    setFileName,
    reportPosition,
    consumeScrollTarget,
    goToPage,
    goToPosition,
    nextPage,
    prevPage,
    zoomIn,
    zoomOut,
  } = usePDF();

  // V1.1.4：三态光标 + 截图选区 + 文本选区共存
  //  - cursorMode='off'        → 默认手型；既无文字选择也无截图
  //  - cursorMode='text'       → I-beam；textLayer pointer-events:auto，浏览器原生 Selection 工作
  //  - cursorMode='screenshot' → crosshair；走 V1.1.3 框选拖拽路径
  // isSelecting 保留为 cursorMode==='screenshot' 的派生量，不再独立 setState（避免双源同步）。
  const [cursorMode, setCursorMode] = useState<CursorMode>('off');
  const isSelecting = cursorMode === 'screenshot';
  const [selectedArea, setSelectedArea] = useState<SelectedArea | null>(null);
  // 无文本层（textLayer 全空）的页号集合。ISSUE-010：按页判定（D9/FE-6），
  // 不再"任一页为空 → 整本判扫描版"（封面/整页图/空白分隔页会误伤正常 PDF）。
  // 用 state 存整个 Set，使 isCurrentPageScanned 能随 currentPage / Set 变化重算。
  const [scanPages, setScanPages] = useState<Set<number>>(new Set());
  // PDFViewer 滚动容器引用，给 useTextSelection 挂 mouseup
  const [pdfContainerEl, setPdfContainerEl] = useState<HTMLDivElement | null>(null);
  const pdfContainerRef = useRef<HTMLDivElement | null>(null);
  pdfContainerRef.current = pdfContainerEl;
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
  // F9 / V1.1.3 F5: 从 library 拿到的上次阅读位置 + 待跳标记。
  // 用 state 而非 ref：library 是异步的，PDF raw 可能命中浏览器缓存先 ready，
  // 必须靠 state 的 re-render 让 restore effect 在 library 完成后再次跑一遍。
  const [pendingRestorePosition, setPendingRestorePosition] = useState<
    { page: number; offset: number } | null
  >(null);
  const [restoreAppliedForPdfId, setRestoreAppliedForPdfId] = useState<string | undefined>(undefined);
  // V1.1.3 F8: 旧用户阅读位置升级一次性 Toast（与 onboarded 同套 localStorage 机制）
  const [readerToast, setReaderToast] = useState<string | null>(null);
  const readerToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  // effect 内先把 ref.current 捕获成局部变量，cleanup 中使用局部变量（react-hooks/exhaustive-deps）。
  useEffect(() => {
    const cards = cardStreamsRef.current;
    const histories = historyStreamsRef.current;
    return () => {
      cards.forEach((h) => h.abort());
      cards.clear();
      histories.forEach((h) => h.abort());
      histories.clear();
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

  usePdfReadingPosition(pdfId, currentPage, currentOffset, restoreAppliedForPdfId === pdfId);

  // Load PDF bytes from backend when pdfId changes.
  useEffect(() => {
    if (!pdfId) return;
    loadPDFFromUrl(getPdfRawUrl(pdfId));
  }, [pdfId, loadPDFFromUrl]);

  // Resolve display name from library list (single-shot — the library endpoint is the source of truth for names).
  // V1.0.4 F9 / V1.1.3 F5: also cache (last_read_page, last_read_offset) for restore-on-open.
  // pendingRestorePosition 语义：null = library 尚未返回；object = 已返回，restore 可推进。
  // 即便位置为 (1, 0)，也必须显式 setPendingRestorePosition，否则 restoreAppliedForPdfId 不会被设，
  // 导致 hook 永久 disabled，用户翻页将无法写入 DB（新书首次阅读场景）。
  useEffect(() => {
    if (!pdfId) return;
    setPendingRestorePosition(null);
    setRestoreAppliedForPdfId(undefined);
    let cancelled = false;
    fetchLibrary().then((items) => {
      if (cancelled) return;
      const match = items.find((item) => item.pdf_id === pdfId);
      if (match) {
        setFileName(match.primary_pdf_filename || match.name);
        const storedPage = match.last_read_page;
        const storedOffset = match.last_read_offset;
        const page = Number.isInteger(storedPage) && storedPage >= 1 ? storedPage : 1;
        const offset =
          Number.isFinite(storedOffset) && storedOffset >= 0 && storedOffset <= 1
            ? storedOffset
            : 0;
        setPendingRestorePosition({ page, offset });
      } else {
        // PDF 不在 library 中（可能是上传后未刷新等边缘场景）：放弃 restore，但仍开闸允许写
        setPendingRestorePosition({ page: 1, offset: 0 });
      }
    }).catch(() => {
      if (!cancelled) setPendingRestorePosition({ page: 1, offset: 0 }); // 网络失败也开闸，避免 hook 永久 disabled
    });
    return () => { cancelled = true; };
  }, [pdfId, setFileName]);

  // F9 / V1.1.3 F5: restore (last_read_page, last_read_offset) once BOTH numPages ready AND pendingRestorePosition resolved.
  // Page clamp 到 [1, numPages]；offset clamp 到 [0, 1]。仅每个 pdfId 触发一次。
  useEffect(() => {
    if (!pdfId || numPages <= 0) return;
    if (restoreAppliedForPdfId === pdfId) return;
    if (pendingRestorePosition === null) return; // library 尚未返回，等下一次 re-render
    const targetPage = Math.min(pendingRestorePosition.page, numPages);
    const targetOffset = pendingRestorePosition.offset;
    if (targetPage > 1 || targetOffset > 0) {
      goToPosition(targetPage, targetOffset);
    }
    setRestoreAppliedForPdfId(pdfId);

    // V1.1.3 F8：旧书首次打开 → 一次性 Toast 提示。
    // 仅当 last_read_offset === 0 时弹（"真正从旧版本升级而来 / 从未在 V1.1.3 写过偏移"）；
    // 新书 / 已写过偏移的书不再弹。localStorage 标记后整个用户范围内只弹一次。
    if (targetOffset === 0) {
      try {
        if (localStorage.getItem(READING_OFFSET_NOTICE_KEY) !== '1') {
          setReaderToast(
            '阅读位置已升级（新增页内偏移），旧书首次打开将从该页顶部恢复，可在阅读中手动定位一次',
          );
          if (readerToastTimerRef.current) clearTimeout(readerToastTimerRef.current);
          readerToastTimerRef.current = setTimeout(() => setReaderToast(null), 5000);
          localStorage.setItem(READING_OFFSET_NOTICE_KEY, '1');
        }
      } catch {
        // localStorage 不可用（隐私模式 / 跨域）：静默跳过；不影响正常阅读
      }
    }
  }, [pdfId, numPages, pendingRestorePosition, restoreAppliedForPdfId, goToPosition]);

  useEffect(() => {
    return () => {
      if (readerToastTimerRef.current) clearTimeout(readerToastTimerRef.current);
    };
  }, []);

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
        setCursorMode('off');
        setScanPages(new Set());
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

  const handleSelectCursorMode = useCallback((mode: CursorMode) => {
    setCursorMode((prev) => {
      if (prev === mode) return prev;
      // 切到 screenshot → 清残留文本选区由 hook enabled=false 自动完成
      // 切到 text / off → 清掉残留截图选区（避免两种 selection 同时存在导致 chips 状态歧义）
      if (mode === 'text' || mode === 'off') {
        setSelectedArea(null);
      }
      return mode;
    });
  }, []);

  const handleSelectionModeExit = useCallback(() => {
    // PDFViewer 内部框选完成 / Esc 退出 → 把 cursorMode 拨回 'off'
    setCursorMode('off');
  }, []);

  const handleSelectionChange = useCallback((area: SelectedArea | null) => {
    setSelectedArea(area);
  }, []);

  // V1.1.4：跨页文本选区 hook（仅在 cursorMode='text' 时挂 mouseup）
  const { selection: textSelection, clear: clearTextSelection } = useTextSelection({
    containerRef: pdfContainerRef,
    enabled: cursorMode === 'text',
  });

  // 无文本层页上报：PDFPage textLayer 渲染完毕若 textContent 为空 → 记入 scanPages。
  // 已在集合内则跳过 setState，避免重复渲染引发的状态风暴。
  const handleScanPageDetected = useCallback((pageNum: number) => {
    setScanPages((prev) => {
      if (prev.has(pageNum)) return prev;
      const next = new Set(prev);
      next.add(pageNum);
      return next;
    });
  }, []);

  // ISSUE-010：仅当"当前所在页"无文本层时才判为不可选文字，而非整本禁用。
  const isCurrentPageScanned = scanPages.has(currentPage);

  // 当前页无文本层且用户正处于 cursorMode='text'，回弹到 'off' 并弹 Toast
  useEffect(() => {
    if (isCurrentPageScanned && cursorMode === 'text') {
      setCursorMode('off');
      setReaderToast('当前页无文本层（可能为扫描页 / 整页图），已退出文字选择模式。如需 AI 处理请使用「截图」。');
      if (readerToastTimerRef.current) clearTimeout(readerToastTimerRef.current);
      readerToastTimerRef.current = setTimeout(() => setReaderToast(null), 5000);
    }
  }, [isCurrentPageScanned, cursorMode]);

  // PDF 切换时重置无文本层页集合
  useEffect(() => {
    setScanPages(new Set());
  }, [pdfId]);

  // Toolbar 点击文字按钮但当前页无文本层时弹一次 Toast（不切 cursorMode）
  const handleTextModeBlockedByScan = useCallback(() => {
    setReaderToast('当前页无文本层（可能为扫描页 / 整页图），无法选择文字。如需 AI 处理请使用「截图」。');
    if (readerToastTimerRef.current) clearTimeout(readerToastTimerRef.current);
    readerToastTimerRef.current = setTimeout(() => setReaderToast(null), 5000);
  }, []);

  // PDFViewer 容器 ref 暴露
  const handleContainerRefReady = useCallback((el: HTMLDivElement | null) => {
    setPdfContainerEl(el);
  }, []);

  const handleTaskTypeToggle = useCallback((type: ChipPluginType) => {
    setActiveTaskTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  }, []);

  // chipsState：image 路径下 dictionary 默认 disabled（前端无法本地求字数，OCR 文本由首轮 extract 产出）；
  // text 路径下若 wordCount<=3 才启用 dictionary（前端可本地统计）。
  // 任一选区（image 或 text）就绪 → translate/explain 可用。
  const hasSelection = !!selectedArea || !!textSelection;
  const dictionaryChip: ChipsState['dictionary'] = textSelection
    ? textSelection.wordCount <= 3
      ? { state: 'available' }
      : { state: 'disabled', reason: '仅支持 3 个词以内的文字选区' }
    : { state: 'disabled', reason: '仅支持 3 个词以内的文字选区' };
  const chipsState: ChipsState = {
    translate: { state: hasSelection ? 'available' : 'disabled' },
    explain: { state: hasSelection ? 'available' : 'disabled' },
    dictionary: dictionaryChip,
  };

  const captureImage = useCallback(async (): Promise<ImageCaptureResult | null> => {
    if (!selectedArea || !pdfDoc) return null;
    // V1.1.3 D-V113-6：以 selectedArea.page（起点页）为基准截图，与 currentPage 解耦
    const targetPage = selectedArea.page;
    const page = await pdfDoc.getPage(targetPage);
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
      kind: 'image',
      dataUrl,
      base64: dataUrl.replace(/^data:image\/png;base64,/, ''),
      width: offCanvas.width,
      height: offCanvas.height,
      selection: {
        page: targetPage,
        x: selectedArea.x * baseViewport.width,
        y: selectedArea.y * baseViewport.height,
        w: selectedArea.width * baseViewport.width,
        h: selectedArea.height * baseViewport.height,
        dpi: 72 * captureScale,
      },
    };
  }, [selectedArea, pdfDoc]);

  // V1.1.4：把 useTextSelection 当前快照转成 TextCaptureResult，便于 handleAIRequest 统一处理
  const captureText = useCallback((): TextCaptureResult | null => {
    if (!textSelection) return null;
    let offset = 0;
    const segments = textSelection.segments.map((seg) => {
      const offset_start = offset;
      const offset_end = offset + seg.text.length;
      offset = offset_end;
      return {
        page: seg.page,
        text: seg.text,
        offset_start,
        offset_end,
      };
    });
    return {
      kind: 'text',
      dataUrl: '',
      text: textSelection.normalizedText,
      pageStart: textSelection.pageStart,
      pageEnd: textSelection.pageEnd,
      segments,
      wordCount: textSelection.wordCount,
    };
  }, [textSelection]);

  const handleAIRequest = useCallback(
    async (taskTypes: ChipPluginType[], inputText?: string) => {
      // V1.1.4：text 选区优先；否则回退 image 选区
      if (!pdfDoc) return;
      const hasText = !!textSelection;
      const hasImage = !!selectedArea;
      if (!hasText && !hasImage) return;
      const trimmedInput = inputText?.trim();
      // V1.1.1：空 chip 列表时需有用户输入才能成立（自由 Chat 模式）
      if (taskTypes.length === 0 && !trimmedInput) return;

      setIsAIWorking(true);
      setAiError(null);
      setActiveTaskTypes([]);

      const cardId = nextMsgId();
      const loadingId = nextMsgId();

      let capture: CaptureResult;
      try {
        if (hasText) {
          const captured = captureText();
          if (!captured) throw new Error('Failed to capture text selection');
          capture = captured;
        } else {
          const captured = await captureImage();
          if (!captured) throw new Error('Failed to capture image');
          capture = captured;
        }
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

      // V1.1.2 screenshot-qa：首轮 OCR 段独立累积；extracted_text 事件到达后视为权威值，后续 ocr delta 丢弃
      let ocrAuthoritative = false;
      const ocrCommitter = createTextDeltaCommitter((appended) => {
        if (ocrAuthoritative) return;
        setAiResults((prev) => {
          const idx = prev.findIndex((r) => r.id === cardId);
          if (idx === -1) return prev;
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            messages: updated[idx].messages.map((m) =>
              m.id === loadingId ? { ...m, ocrText: (m.ocrText || '') + appended } : m,
            ),
          };
          return updated;
        });
      });

      const finalize = () => {
        committer.reset();
        ocrCommitter.reset();
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
              // V1.1.2：后端按 image 自动激活 screenshot-qa；前端按 meta.task_type 落库 type
              type: meta.task_type ?? updated[idx].type,
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId
                  ? { ...m, isLoading: false, isStreaming: true }
                  : m,
              ),
            };
            return updated;
          });
        },
        onTextDelta: (delta, section) => {
          if (section === 'ocr') ocrCommitter.push(delta);
          else committer.push(delta);
        },
        onExtractedText: (text) => {
          ocrAuthoritative = true;
          ocrCommitter.reset();
          setAiResults((prev) => {
            const idx = prev.findIndex((r) => r.id === cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId ? { ...m, ocrText: text, ocrAuthoritative: true } : m,
              ),
            };
            return updated;
          });
        },
        onUsage: () => { /* 本任务不在 UI 持久化 usage；后端落 DB 即可 */ },
        onDone: () => {
          committer.flushNow();
          ocrCommitter.flushNow();
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
        capture.kind === 'image'
          ? ({
              kind: 'image',
              selection: capture.selection,
              image: { data: capture.base64, width: capture.width, height: capture.height },
            } as FirstTurnSelection)
          : ({
              kind: 'text',
              selection: {
                page: capture.pageStart,
                page_end: capture.pageEnd,
                text: capture.text,
                segments: capture.segments,
              },
            } as FirstTurnSelection),
        { targetLang: 'zh-CN', userInput: trimmedInput, pdfId },
        callbacks,
      );
      cardStreamsRef.current.set(cardId, handle);
    },
    [selectedArea, textSelection, pdfDoc, captureImage, captureText, pdfId],
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

        // V1.1.2 screenshot-qa：重试首轮也需要 OCR 通道
        let ocrAuthoritative = false;
        const ocrCommitter = createTextDeltaCommitter((appended) => {
          if (ocrAuthoritative) return;
          setAiResults((prev) => {
            const idx = prev.findIndex((c) => c.id === r.cardId);
            if (idx === -1) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              messages: updated[idx].messages.map((m) =>
                m.id === loadingId ? { ...m, ocrText: (m.ocrText || '') + appended } : m,
              ),
            };
            return updated;
          });
        });

        const finalize = () => {
          committer.reset();
          ocrCommitter.reset();
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
                type: meta.task_type ?? updated[idx].type,
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, isLoading: false, isStreaming: true } : m,
                ),
              };
              return updated;
            });
          },
          onTextDelta: (delta, section) => {
            if (section === 'ocr') ocrCommitter.push(delta);
            else committer.push(delta);
          },
          onExtractedText: (text) => {
            ocrAuthoritative = true;
            ocrCommitter.reset();
            setAiResults((prev) => {
              const idx = prev.findIndex((c) => c.id === r.cardId);
              if (idx === -1) return prev;
              const updated = [...prev];
              updated[idx] = {
                ...updated[idx],
                messages: updated[idx].messages.map((m) =>
                  m.id === loadingId ? { ...m, ocrText: text, ocrAuthoritative: true } : m,
                ),
              };
              return updated;
            });
          },
          onUsage: () => {},
          onDone: () => {
            committer.flushNow();
            ocrCommitter.flushNow();
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
          r.capture.kind === 'image'
            ? ({
                kind: 'image',
                selection: r.capture.selection,
                image: { data: r.capture.base64, width: r.capture.width, height: r.capture.height },
              } as FirstTurnSelection)
            : ({
                kind: 'text',
                selection: {
                  page: r.capture.pageStart,
                  page_end: r.capture.pageEnd,
                  text: r.capture.text,
                  segments: r.capture.segments,
                },
              } as FirstTurnSelection),
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

  // V1.1.2 screenshot-qa：识别文本折叠区切换。点击切换 ocrCollapsed；msg.id 是稳定标识。
  const handleToggleOcr = useCallback((msg: Message) => {
    const toggle = (m: Message): Message =>
      m.id === msg.id ? { ...m, ocrCollapsed: !(m.ocrCollapsed === true) } : m;
    setAiResults((prev) =>
      prev.map((card) => ({ ...card, messages: card.messages.map(toggle) })),
    );
    setHistory((prev) => prev.map((h) => ({ ...h, messages: h.messages.map(toggle) })));
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
        cursorMode={cursorMode}
        isCurrentPageScanned={isCurrentPageScanned}
        onOpenFile={handleOpenFile}
        onPrevPage={prevPage}
        onNextPage={nextPage}
        onGoToPage={goToPage}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onSelectCursorMode={handleSelectCursorMode}
        onTextModeBlockedByScan={handleTextModeBlockedByScan}
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
          numPages={numPages}
          scale={scale}
          isLoading={isLoading}
          error={pdfError}
          onSelectionChange={handleSelectionChange}
          selectedArea={selectedArea}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          isSelecting={isSelecting}
          onSelectionModeExit={handleSelectionModeExit}
          pendingScrollTarget={pendingScrollTarget}
          onScrollTargetConsumed={consumeScrollTarget}
          onPositionChange={reportPosition}
          cursorMode={cursorMode}
          onScanPageDetected={handleScanPageDetected}
          onContainerRefReady={handleContainerRefReady}
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
          hasSelection={hasSelection}
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
          onToggleOcr={handleToggleOcr}
        />
      </div>

      {readerToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 pointer-events-none">
          <div className="bg-stone-800 text-white text-sm px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-2 animate-[fadeInUp_0.2s_ease-out] max-w-[520px]">
            <i className="ri-information-line text-amber-400 text-sm"></i>
            <span className="leading-relaxed">{readerToast}</span>
          </div>
        </div>
      )}
    </div>
  );
}

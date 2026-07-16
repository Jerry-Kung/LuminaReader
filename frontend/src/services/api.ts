const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export type TaskType = 'translate' | 'explain' | 'dictionary' | 'chat' | 'screenshot-qa';

// V1.1.2: SSE text_delta.section 字段（screenshot-qa 路径流式分段）
export type StreamSection = 'ocr' | 'answer';

export interface TranslateSelection {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  dpi: number;
}

// V1.1.4：文字选区上行结构（与后端 SelectionSegment / Selection type='text' 对齐）
export interface TextSelectionSegmentPayload {
  page: number;
  text: string;
  offset_start: number;
  offset_end: number;
}

export interface TextSelectionPayload {
  page: number;
  page_end: number;
  text: string;
  segments: TextSelectionSegmentPayload[];
}

// V1.1.4：首轮 selection 三态：截图 / 文字 / null（追问）
export type FirstTurnSelection =
  | { kind: 'image'; selection: TranslateSelection; image: TranslateImage }
  | { kind: 'text'; selection: TextSelectionPayload };

export interface TranslateImage {
  data: string;
  width: number;
  height: number;
}

export interface TranslateMeta {
  request_id?: string;
  model?: string;
  latency_ms?: number;
  task_type?: TaskType;
  turn_index?: number;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

export interface RunOptions {
  targetLang?: string;
  userQuestion?: string;
  userInput?: string;
  pdfId?: string;
}

interface SuccessEnvelope<T> {
  ok: true;
  data: T;
}

interface ErrorEnvelope {
  ok: false;
  error: {
    code: string;
    message: string;
    request_id?: string;
    [key: string]: unknown;
  };
}

type Envelope<T> = SuccessEnvelope<T> | ErrorEnvelope;

export class TranslateApiError extends Error {
  code: string;
  requestId?: string;
  httpStatus?: number;
  retriable?: boolean;

  constructor(
    code: string,
    message: string,
    requestId?: string,
    httpStatus?: number,
    retriable?: boolean,
  ) {
    super(message);
    this.code = code;
    this.requestId = requestId;
    this.httpStatus = httpStatus;
    this.retriable = retriable;
  }
}

// =====================================================================
// V1.1.0 F1：SSE 流式 API（取代 V1.0.x 的 runTask / runFollowUp 一次性 POST）
// 后端契约见 claude_docs/api-contract.md §4.2.2
// =====================================================================

export interface StreamMeta {
  request_id: string;
  session_id: string;
  conversation_id: string;
  task_type: TaskType;
  turn_index: number;
  model: string;
  thinking_enabled: boolean;
  plugins?: string[];
  extract_latency_ms?: number;
}

export interface StreamUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface RunStreamCallbacks {
  onMeta: (meta: StreamMeta) => void;
  // V1.1.2：text_delta.section 用于区分 OCR 折叠区 / 正文区流式累积；其他插件路径恒为 null
  onTextDelta: (delta: string, section: StreamSection | null) => void;
  // V1.1.2：仅 screenshot-qa 路径下发；text 是 OCR 段全部收完后的"权威值"，前端折叠区据此覆盖
  onExtractedText?: (text: string) => void;
  onUsage: (usage: StreamUsage) => void;
  onDone: (final: { latency_ms: number }) => void;
  // partialTextKept: 后端已把累积文本落库（含 [interrupted] 标记）；前端 partial 气泡可保留
  onError: (err: TranslateApiError, opts: { partialTextKept: boolean }) => void;
}

export interface RunStreamHandle {
  abort: () => void;
}

const MOCK_TEXTS: Record<TaskType, string> = {
  translate:
    '这是模拟的翻译结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 翻译的实际内容。\n\n您可以框选 PDF 中的英文段落，点击 Run 按钮，AI 将为您把选区内容翻译为简体中文。',
  explain:
    '这是模拟的解释结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 对所选内容的深度解读，包括：核心观点、术语说明、必要的背景知识。',
  dictionary:
    '这是模拟的词典结果。\n\n选中 1–3 个词时，AI 会返回该词的发音、词性、释义、词源与例句。',
  chat:
    '这是模拟的自由对话回答。\n\n不选任何能力 chip 直接输入问题时,AI 会作为你的阅读助手回答提问,并参考所框选的上下文。',
  'screenshot-qa':
    '这是模拟的截图问答回答。\n\n当后端启用且选区含图像时,AI 会先 OCR 识别文本再据此回答你的提问。',
};

const mockTurnCounter: Record<string, number> = {};

function mockRunStream(
  plugins: TaskType[],
  sessionId: string,
  userInput: string | undefined,
  isFollowUp: boolean,
  callbacks: RunStreamCallbacks,
): RunStreamHandle {
  let aborted = false;
  const timers: ReturnType<typeof setTimeout>[] = [];
  const conversationId = isFollowUp ? sessionId : `mock-${Date.now()}`;
  const turnIndex = mockTurnCounter[conversationId] ?? 0;
  mockTurnCounter[conversationId] = turnIndex + 1;
  // 用 plugins[0] 决定 mock 文本；plugins 为空时走 chat
  const primary: TaskType = plugins[0] ?? 'chat';
  const baseText = turnIndex === 0 ? MOCK_TEXTS[primary] : '这是模拟的追问回答。';
  const fullText = userInput ? `（针对你的问题：「${userInput}」）\n\n${baseText}` : baseText;
  // 切成 5 段模拟流式
  const chunkSize = Math.max(1, Math.ceil(fullText.length / 5));
  const chunks: string[] = [];
  for (let i = 0; i < fullText.length; i += chunkSize) chunks.push(fullText.slice(i, i + chunkSize));

  const start = performance.now();
  timers.push(setTimeout(() => {
    if (aborted) return;
    const meta: StreamMeta = {
      request_id: `mock-req-${Date.now()}`,
      session_id: conversationId,
      conversation_id: conversationId,
      task_type: primary,
      turn_index: turnIndex,
      model: 'mock',
      thinking_enabled: false,
      plugins: plugins.slice(),
      ...(isFollowUp ? {} : { extract_latency_ms: 200 }),
    };
    callbacks.onMeta(meta);
  }, 200));

  chunks.forEach((c, i) => {
    timers.push(setTimeout(() => {
      if (aborted) return;
      callbacks.onTextDelta(c, null);
    }, 350 + i * 60));
  });

  timers.push(setTimeout(() => {
    if (aborted) return;
    callbacks.onUsage({ prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 });
    callbacks.onDone({ latency_ms: Math.round(performance.now() - start) });
  }, 350 + chunks.length * 60 + 40));

  return {
    abort: () => {
      aborted = true;
      timers.forEach(clearTimeout);
    },
  };
}

interface SSEParseState {
  buffer: string;
  doneSeen: boolean;
  textChunkCount: number;
  errorCode?: string;
}

function parseSSEFrame(rawFrame: string, callbacks: RunStreamCallbacks, state: SSEParseState): void {
  if (state.doneSeen) return;
  // 兼容 \r\n
  const frame = rawFrame.replace(/\r/g, '');
  if (!frame) return;
  // 心跳/注释帧
  if (frame.startsWith(':')) return;

  const lines = frame.split('\n');
  let event = '';
  let data = '';
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data = line.slice(5).trim();
    // 其他字段（id: / retry:）忽略
  }
  if (!event || !data) return;

  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    state.doneSeen = true;
    callbacks.onError(
      new TranslateApiError('INVALID_RESPONSE', `Malformed SSE frame: ${event}`),
      { partialTextKept: state.textChunkCount > 0 },
    );
    return;
  }
  const obj = parsed as Record<string, unknown>;

  switch (event) {
    case 'meta':
      callbacks.onMeta(obj as unknown as StreamMeta);
      break;
    case 'text_delta': {
      const delta = typeof obj.delta === 'string' ? obj.delta : '';
      // V1.1.2：section 字段缺省视作 null（V1.1.1 兼容路径）；只接受合法字面值
      const rawSection = obj.section;
      const section: StreamSection | null =
        rawSection === 'ocr' || rawSection === 'answer' ? rawSection : null;
      if (delta) {
        state.textChunkCount += 1;
        callbacks.onTextDelta(delta, section);
      }
      break;
    }
    case 'extracted_text': {
      // V1.1.2：screenshot-qa 路径独有；text 为 OCR 段完整权威值
      const text = typeof obj.text === 'string' ? obj.text : '';
      callbacks.onExtractedText?.(text);
      break;
    }
    case 'usage':
      callbacks.onUsage(obj as unknown as StreamUsage);
      break;
    case 'done':
      state.doneSeen = true;
      callbacks.onDone({ latency_ms: typeof obj.latency_ms === 'number' ? obj.latency_ms : 0 });
      break;
    case 'error': {
      state.doneSeen = true;
      const code = typeof obj.code === 'string' ? obj.code : 'STREAM_INTERRUPTED';
      const message = typeof obj.message === 'string' ? obj.message : 'Stream interrupted.';
      const retriable = obj.retriable === true;
      const partialKept = obj.partial_text_kept === true;
      state.errorCode = code;
      const err = new TranslateApiError(code, message, undefined, undefined, retriable);
      callbacks.onError(err, { partialTextKept: partialKept });
      break;
    }
    default:
      // 未知事件：忽略
      break;
  }
}

async function consumeSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  callbacks: RunStreamCallbacks,
): Promise<void> {
  const decoder = new TextDecoder('utf-8', { fatal: false });
  const state: SSEParseState = { buffer: '', doneSeen: false, textChunkCount: 0 };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      state.buffer += decoder.decode(value, { stream: true });

      let idx: number;
      while ((idx = state.buffer.indexOf('\n\n')) !== -1) {
        const frame = state.buffer.slice(0, idx);
        state.buffer = state.buffer.slice(idx + 2);
        parseSSEFrame(frame, callbacks, state);
        if (state.doneSeen) {
          // done / error 后丢弃后续 buffer
          state.buffer = '';
          return;
        }
      }
    }
    // 流自然结束：flush decoder + 末尾不完整帧兜底
    state.buffer += decoder.decode();
    if (state.buffer.trim() && !state.doneSeen) {
      parseSSEFrame(state.buffer, callbacks, state);
    }
    // 走到这里仍没 done / error：视为流被截断
    if (!state.doneSeen) {
      callbacks.onError(
        new TranslateApiError('STREAM_INTERRUPTED', 'Stream ended without done event.', undefined, undefined, true),
        { partialTextKept: state.textChunkCount > 0 },
      );
    }
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError') return; // abort 静默
    if (state.doneSeen) return;
    const msg = err instanceof Error ? err.message : 'Stream read failed.';
    callbacks.onError(
      new TranslateApiError('NETWORK_ERROR', msg, undefined, undefined, true),
      { partialTextKept: state.textChunkCount > 0 },
    );
  }
}

function startSSEFetch(
  url: string,
  body: Record<string, unknown>,
  callbacks: RunStreamCallbacks,
): RunStreamHandle {
  const ac = new AbortController();
  let finished = false;
  const wrap: RunStreamCallbacks = {
    onMeta: (m) => { if (!finished) callbacks.onMeta(m); },
    onTextDelta: (d, s) => { if (!finished) callbacks.onTextDelta(d, s); },
    onExtractedText: (t) => { if (!finished) callbacks.onExtractedText?.(t); },
    onUsage: (u) => { if (!finished) callbacks.onUsage(u); },
    onDone: (f) => { if (finished) return; finished = true; callbacks.onDone(f); },
    onError: (e, o) => { if (finished) return; finished = true; callbacks.onError(e, o); },
  };

  (async () => {
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify(body),
        cache: 'no-store',
        signal: ac.signal,
      });
    } catch (err) {
      if ((err as { name?: string })?.name === 'AbortError') return;
      const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
      wrap.onError(new TranslateApiError('NETWORK_ERROR', msg, undefined, undefined, true), {
        partialTextKept: false,
      });
      return;
    }

    const ct = (response.headers.get('content-type') || '').toLowerCase();
    const isSSE = response.ok && ct.startsWith('text/event-stream');

    if (!isSSE) {
      // STREAM_UNSUPPORTED 等 JSON 信封路径
      let envelope: unknown = null;
      try {
        envelope = await response.json();
      } catch {
        wrap.onError(
          new TranslateApiError(
            'INVALID_RESPONSE',
            `Backend returned non-JSON response (HTTP ${response.status}).`,
            undefined,
            response.status,
          ),
          { partialTextKept: false },
        );
        return;
      }
      const env = envelope as Envelope<unknown>;
      if (env && env.ok === true) {
        // 不应到达——options.stream=true 时后端应返 SSE；防御性处理
        wrap.onError(
          new TranslateApiError('INVALID_RESPONSE', 'Expected SSE but got JSON success envelope.'),
          { partialTextKept: false },
        );
        return;
      }
      const errorBody = env && env.ok === false ? env.error : undefined;
      wrap.onError(
        new TranslateApiError(
          errorBody?.code || 'INTERNAL_ERROR',
          errorBody?.message || `Request failed (HTTP ${response.status}).`,
          errorBody?.request_id,
          response.status,
          false,
        ),
        { partialTextKept: false },
      );
      return;
    }

    if (!response.body) {
      wrap.onError(
        new TranslateApiError('INVALID_RESPONSE', 'SSE response missing body.'),
        { partialTextKept: false },
      );
      return;
    }
    const reader = response.body.getReader();
    await consumeSSE(reader, wrap);
  })();

  return {
    abort: () => {
      if (finished) return;
      finished = true;
      ac.abort();
    },
  };
}

function buildFirstTurnBody(
  plugins: TaskType[],
  firstTurn: FirstTurnSelection,
  options: RunOptions,
): Record<string, unknown> {
  // V1.1.1 契约：plugins[] + user_input 为新字段；task_type 仍必填（后端用作回退）。
  // 空 plugins → 走 chat 模式，task_type 传 "chat" 让后端 resolve_plugin_routing 走空 plugin 分支。
  // V1.1.4：selection 区分 image / text；text 路径 image=null，selection 含 type/text/page_end/segments。
  const taskType: TaskType = plugins[0] ?? 'chat';
  if (firstTurn.kind === 'image') {
    const { selection, image } = firstTurn;
    return {
      task_type: taskType,
      plugins,
      user_input: options.userInput ?? null,
      session_id: null,
      pdf_id: options.pdfId ?? null,
      selection: {
        type: 'image',
        pdf_id: options.pdfId ?? null,
        page: selection.page,
        x: selection.x,
        y: selection.y,
        w: selection.w,
        h: selection.h,
        dpi: selection.dpi,
      },
      image: {
        mime: 'image/png',
        data: image.data,
        width: image.width,
        height: image.height,
      },
      options: {
        target_lang: options.targetLang ?? 'zh-CN',
        user_question: options.userQuestion ?? null,
        stream: true,
      },
    };
  }
  // text 路径
  const { selection } = firstTurn;
  return {
    task_type: taskType,
    plugins,
    user_input: options.userInput ?? null,
    session_id: null,
    pdf_id: options.pdfId ?? null,
    selection: {
      type: 'text',
      pdf_id: options.pdfId ?? null,
      page: selection.page,
      page_end: selection.page_end,
      text: selection.text,
      segments: selection.segments,
    },
    image: null,
    options: {
      target_lang: options.targetLang ?? 'zh-CN',
      user_question: options.userQuestion ?? null,
      stream: true,
    },
  };
}

function buildFollowUpBody(
  plugins: TaskType[],
  sessionId: string,
  userInput: string,
  options: { targetLang?: string },
): Record<string, unknown> {
  // 追问轮：plugins 可与首轮不同（V1.1.1 起跨插件追问已允许，SESSION_TASK_MISMATCH 已移除）。
  // task_type 字段仍传 plugins[0] ?? 'chat' 维持必填。
  const taskType: TaskType = plugins[0] ?? 'chat';
  return {
    task_type: taskType,
    plugins,
    user_input: userInput,
    session_id: sessionId,
    selection: null,
    image: null,
    options: {
      target_lang: options.targetLang ?? 'zh-CN',
      user_question: userInput,
      stream: true,
    },
  };
}

// First turn streaming: selection 必填（image 或 text），其中 image 路径附带 PNG payload。
// V1.1.4：text 路径 selection.kind='text'，image 不再传，后端依据 selection.type='text' 跳过 OCR。
export function runTaskStream(
  plugins: TaskType[],
  firstTurn: FirstTurnSelection,
  options: RunOptions,
  callbacks: RunStreamCallbacks,
): RunStreamHandle {
  if (!API_BASE) {
    return mockRunStream(plugins, '', options.userInput, false, callbacks);
  }
  return startSSEFetch(`${API_BASE}/api/v1/run`, buildFirstTurnBody(plugins, firstTurn, options), callbacks);
}

// Follow-up streaming: text-driven only (Scheme D).
export function runFollowUpStream(
  plugins: TaskType[],
  sessionId: string,
  userInput: string,
  options: { targetLang?: string },
  callbacks: RunStreamCallbacks,
): RunStreamHandle {
  if (!API_BASE) {
    return mockRunStream(plugins, sessionId, userInput, true, callbacks);
  }
  return startSSEFetch(`${API_BASE}/api/v1/run`, buildFollowUpBody(plugins, sessionId, userInput, options), callbacks);
}

// Release a session ("clear conversation"). 204 = deleted, 404 = already gone — both resolve.
export async function clearSession(sessionId: string): Promise<void> {
  if (!API_BASE) {
    delete mockTurnCounter[sessionId];
    return;
  }

  const url = `${API_BASE}/api/v1/sessions/${encodeURIComponent(sessionId)}`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'DELETE' });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }

  if (response.status === 204 || response.status === 404) return;

  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  throw new TranslateApiError(
    envelope?.error?.code || 'INTERNAL_ERROR',
    envelope?.error?.message || `Failed to clear session (HTTP ${response.status}).`,
    envelope?.error?.request_id,
    response.status,
  );
}

// =====================================================================
// V1.0.3 library / pdfs / conversations endpoints
// =====================================================================

export interface LibraryItem {
  pdf_id: string;
  name: string;
  primary_pdf_filename: string;
  primary_pdf_size: number;
  created_at: number;
  last_opened_at: number;
  last_read_page: number;
  // V1.1.3 F5：页内偏移（0 ~ 1 相对值，与 scale 解耦）。旧后端响应中缺该字段时回退 0。
  last_read_offset: number;
  thumbnail_url: string | null;
}

export interface PdfUploadResult {
  pdf_id: string;
  project_id: string;
  name: string;
  primary_pdf_filename: string;
  primary_pdf_size: number;
  created_at: number;
}

export interface ConflictExisting {
  pdf_id: string;
  name: string;
  primary_pdf_filename: string;
  primary_pdf_size: number;
  created_at: number;
  last_opened_at: number;
}

export class PdfConflictError extends TranslateApiError {
  existing: ConflictExisting;
  forceCreateNewHint?: string;

  constructor(
    message: string,
    existing: ConflictExisting,
    forceCreateNewHint: string | undefined,
    requestId?: string,
  ) {
    super('PROJECT_NAME_CONFLICT', message, requestId, 409);
    this.existing = existing;
    this.forceCreateNewHint = forceCreateNewHint;
  }
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

export interface SelectionCoord {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ConversationSummary {
  conversation_id: string;
  task_type: TaskType;
  selection: SelectionCoord;
  thumbnail_url: string | null;
  first_assistant_summary: string;
  status: string;
  created_at: number;
  last_used_at: number;
  message_count: number;
}

export interface MessageItem {
  message_id: string;
  turn_index: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: number;
  user_question?: string;
  model?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
  latency_ms?: number;
}

export interface ConversationDetail {
  conversation_id: string;
  task_type: TaskType;
  extracted_text: string;
  messages: MessageItem[];
}

async function parseEnvelope<T>(response: Response): Promise<T> {
  let envelope: Envelope<T>;
  try {
    envelope = await response.json();
  } catch {
    throw new TranslateApiError(
      'INVALID_RESPONSE',
      `Backend returned non-JSON response (HTTP ${response.status}).`,
      undefined,
      response.status,
    );
  }
  if (envelope.ok === true) return envelope.data;
  throw new TranslateApiError(
    envelope.error?.code || 'INTERNAL_ERROR',
    envelope.error?.message || `Request failed (HTTP ${response.status}).`,
    envelope.error?.request_id,
    response.status,
  );
}

export type LibrarySort = 'last_opened_at_desc' | 'created_at_desc' | 'name_asc';

export async function fetchLibrary(sort: LibrarySort = 'last_opened_at_desc'): Promise<LibraryItem[]> {
  if (!API_BASE) return [];
  const url = `${API_BASE}/api/v1/library?sort=${encodeURIComponent(sort)}`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  const data = await parseEnvelope<{ items: LibraryItem[] }>(response);
  return data.items;
}

// Upload a PDF (multipart). Throws PdfConflictError on 409.
// Use XHR for upload progress events.
export async function uploadPdf(
  file: File,
  options: {
    forceCreateNew?: boolean;
    onProgress?: (progress: UploadProgress) => void;
  } = {},
): Promise<PdfUploadResult> {
  if (!API_BASE) {
    throw new TranslateApiError(
      'NO_BACKEND',
      'Upload requires VITE_API_BASE_URL to be configured.',
    );
  }

  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append('file', file);
    if (options.forceCreateNew) {
      formData.append('force_create_new', 'true');
    }

    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && options.onProgress) {
        options.onProgress({
          loaded: e.loaded,
          total: e.total,
          percentage: Math.round((e.loaded / e.total) * 100),
        });
      }
    });

    xhr.addEventListener('load', () => {
      let envelope: Envelope<PdfUploadResult> | null = null;
      try {
        envelope = JSON.parse(xhr.responseText);
      } catch {
        reject(
          new TranslateApiError(
            'INVALID_RESPONSE',
            `Upload returned non-JSON response (HTTP ${xhr.status}).`,
            undefined,
            xhr.status,
          ),
        );
        return;
      }

      if (envelope && envelope.ok === true) {
        resolve(envelope.data);
        return;
      }

      const errorBody = envelope && envelope.ok === false ? envelope.error : null;
      if (xhr.status === 409 && errorBody && errorBody.code === 'PROJECT_NAME_CONFLICT') {
        const existing = errorBody.existing as ConflictExisting | undefined;
        if (existing) {
          reject(
            new PdfConflictError(
              errorBody.message || '已存在同名书',
              existing,
              errorBody.force_create_new_hint as string | undefined,
              errorBody.request_id,
            ),
          );
          return;
        }
      }
      reject(
        new TranslateApiError(
          errorBody?.code || 'INTERNAL_ERROR',
          errorBody?.message || `Upload failed (HTTP ${xhr.status}).`,
          errorBody?.request_id,
          xhr.status,
        ),
      );
    });

    xhr.addEventListener('error', () => {
      reject(new TranslateApiError('NETWORK_ERROR', 'Upload network error.'));
    });
    xhr.addEventListener('abort', () => {
      reject(new TranslateApiError('UPLOAD_ABORTED', 'Upload aborted.'));
    });

    xhr.open('POST', `${API_BASE}/api/v1/pdfs`);
    xhr.send(formData);
  });
}

export async function deletePdf(pdfId: string): Promise<void> {
  if (!API_BASE) return;
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'DELETE' });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  if (response.status === 204 || response.status === 404) return;
  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  throw new TranslateApiError(
    envelope?.error?.code || 'INTERNAL_ERROR',
    envelope?.error?.message || `Failed to delete pdf (HTTP ${response.status}).`,
    envelope?.error?.request_id,
    response.status,
  );
}

export function getPdfRawUrl(pdfId: string): string {
  return `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/raw`;
}

// V1.0.4 F9 / V1.1.3 F5: persist last_read_page + last_read_offset. 204/404 both resolve; 400 throws.
// lastReadOffset：0 ~ 1 相对值，缺省 0；越界 / 类型错误 → 400 INVALID_REQUEST。
export async function updateReadingPosition(
  pdfId: string,
  lastReadPage: number,
  lastReadOffset: number = 0,
): Promise<void> {
  if (!API_BASE) return;
  if (!Number.isInteger(lastReadPage) || lastReadPage < 1) {
    throw new TranslateApiError(
      'INVALID_REQUEST',
      `last_read_page must be a positive integer (got ${lastReadPage}).`,
    );
  }
  if (
    !Number.isFinite(lastReadOffset) ||
    lastReadOffset < 0 ||
    lastReadOffset > 1
  ) {
    throw new TranslateApiError(
      'INVALID_REQUEST',
      `last_read_offset must be in [0, 1] (got ${lastReadOffset}).`,
    );
  }
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/reading-position`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        last_read_page: lastReadPage,
        last_read_offset: lastReadOffset,
      }),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  if (response.status === 204 || response.status === 404) return;
  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  throw new TranslateApiError(
    envelope?.error?.code || 'INTERNAL_ERROR',
    envelope?.error?.message || `Failed to update reading position (HTTP ${response.status}).`,
    envelope?.error?.request_id,
    response.status,
  );
}

// V1.2.1：全书文本提取状态 / 手动触发（GET / POST /api/v1/pdfs/{id}/text-extraction）

export type TextExtractionStatus = 'none' | 'pending' | 'ok' | 'unsupported' | 'failed';

export interface TextExtractionInfo {
  pdf_id: string;
  status: TextExtractionStatus;
  page_count: number | null;
  textual_page_count: number | null;
  char_count: number | null;
  extracted_at: number | null;
  error: string | null;
}

export async function getTextExtraction(pdfId: string): Promise<TextExtractionInfo> {
  if (!API_BASE) {
    return {
      pdf_id: pdfId,
      status: 'ok',
      page_count: null,
      textual_page_count: null,
      char_count: null,
      extracted_at: null,
      error: null,
    };
  }
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/text-extraction`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  return parseEnvelope<TextExtractionInfo>(response);
}

export async function triggerTextExtraction(pdfId: string): Promise<void> {
  if (!API_BASE) return;
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/text-extraction`;
  let response: Response;
  try {
    response = await fetch(url, { method: 'POST' });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  if (response.status === 202) return;
  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  throw new TranslateApiError(
    envelope?.error?.code || 'INTERNAL_ERROR',
    envelope?.error?.message || `Failed to trigger text extraction (HTTP ${response.status}).`,
    envelope?.error?.request_id,
    response.status,
  );
}

export async function listConversations(pdfId: string): Promise<ConversationSummary[]> {
  if (!API_BASE) return [];
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/conversations`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  const data = await parseEnvelope<{ items: ConversationSummary[] }>(response);
  return data.items.filter((c) => c.status === 'active');
}

export async function listMessages(conversationId: string): Promise<ConversationDetail> {
  if (!API_BASE) {
    return { conversation_id: conversationId, task_type: 'translate', extracted_text: '', messages: [] };
  }
  const url = `${API_BASE}/api/v1/conversations/${encodeURIComponent(conversationId)}/messages`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  return parseEnvelope<ConversationDetail>(response);
}

// V1.0.4 F3: settings 契约客户端（GET/PUT /api/v1/settings，§10.9）
// 后端权威结构见 claude_docs/api-contract.md §10.9.1 / §10.9.2 / §10.9.3。

export type ProviderKind = 'openai_compat';

export interface SettingsProvider {
  kind: ProviderKind;
  base_url: string;
  api_key_masked: string | null;
  default_model: string;
  timeout_seconds: number;
}

export interface SettingsTaskModels {
  extract: string | null;
  translate: string | null;
  explain: string | null;
}

export interface SettingsThinking {
  enabled: boolean;
}

// V1.2.1：跨页自动上下文开关
export interface SettingsContextExpansion {
  enabled: boolean;
}

export interface SettingsSource {
  provider: SettingsProvider;
  task_models: SettingsTaskModels;
  thinking: SettingsThinking;
  context_expansion: SettingsContextExpansion;
  source: 'user_data' | 'env_fallback';
  writable: boolean;
  provider_ready: boolean;
}

export interface SettingsFieldError {
  path: string;
  reason: string;
}

export type ApiKeyIntent =
  | { kind: 'keep' }
  | { kind: 'clear' }
  | { kind: 'replace'; value: string };

export interface SettingsUpdateInput {
  base_url: string;
  default_model: string;
  timeout_seconds: number;
  task_models: SettingsTaskModels;
  thinking: SettingsThinking;
  context_expansion: SettingsContextExpansion;
  api_key: ApiKeyIntent;
}

export type SaveSettingsResult =
  | { kind: 'ok'; data: SettingsSource }
  | { kind: 'invalid'; message: string; fieldErrors: SettingsFieldError[]; requestId?: string }
  | { kind: 'persist_failed'; message: string; requestId?: string }
  | { kind: 'network_error'; message: string }
  | { kind: 'unknown_error'; message: string; code?: string; httpStatus?: number; requestId?: string };

export async function getSettings(): Promise<SettingsSource> {
  if (!API_BASE) {
    return {
      provider: {
        kind: 'openai_compat',
        base_url: 'https://api.openai.com/v1',
        api_key_masked: null,
        default_model: 'gpt-4o',
        timeout_seconds: 60,
      },
      task_models: { extract: null, translate: null, explain: null },
      thinking: { enabled: false },
      context_expansion: { enabled: true },
      source: 'env_fallback',
      writable: false,
      provider_ready: false,
    };
  }
  const url = `${API_BASE}/api/v1/settings`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  return parseEnvelope<SettingsSource>(response);
}

export async function saveSettings(input: SettingsUpdateInput): Promise<SaveSettingsResult> {
  const provider: Record<string, unknown> = {
    kind: 'openai_compat',
    base_url: input.base_url,
    default_model: input.default_model,
    timeout_seconds: input.timeout_seconds,
  };
  if (input.api_key.kind === 'clear') {
    provider.api_key = null;
  } else if (input.api_key.kind === 'replace') {
    provider.api_key = input.api_key.value;
  }

  const body = {
    provider,
    task_models: {
      extract: input.task_models.extract,
      translate: input.task_models.translate,
      explain: input.task_models.explain,
    },
    thinking: {
      enabled: input.thinking.enabled,
    },
    context_expansion: {
      enabled: input.context_expansion.enabled,
    },
  };

  if (!API_BASE) {
    if (!input.base_url.startsWith('http://') && !input.base_url.startsWith('https://')) {
      return {
        kind: 'invalid',
        message: '请输入合法的 http(s) 地址',
        fieldErrors: [{ path: 'provider.base_url', reason: '请输入合法的 http(s) 地址' }],
      };
    }
    if (input.timeout_seconds < 5 || input.timeout_seconds > 300) {
      return {
        kind: 'invalid',
        message: '超时秒数应在 5 到 300 之间',
        fieldErrors: [
          { path: 'provider.timeout_seconds', reason: '超时秒数应在 5 到 300 之间' },
        ],
      };
    }
    return {
      kind: 'ok',
      data: {
        provider: {
          kind: 'openai_compat',
          base_url: input.base_url,
          api_key_masked:
            input.api_key.kind === 'clear'
              ? null
              : input.api_key.kind === 'replace'
                ? `sk-***...${input.api_key.value.slice(-4)}`
                : null,
          default_model: input.default_model,
          timeout_seconds: input.timeout_seconds,
        },
        task_models: input.task_models,
        thinking: input.thinking,
        context_expansion: input.context_expansion,
        source: 'user_data',
        writable: true,
        provider_ready: input.api_key.kind === 'replace',
      },
    };
  }

  const url = `${API_BASE}/api/v1/settings`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    return { kind: 'network_error', message: msg };
  }

  let envelope: unknown;
  try {
    envelope = await response.json();
  } catch {
    return {
      kind: 'unknown_error',
      message: `Backend returned non-JSON response (HTTP ${response.status}).`,
      httpStatus: response.status,
    };
  }

  if (response.ok) {
    const env = envelope as SuccessEnvelope<SettingsSource>;
    return { kind: 'ok', data: env.data };
  }

  const errEnv = envelope as ErrorEnvelope;
  const code = errEnv?.error?.code;
  const message = errEnv?.error?.message || `保存失败 (HTTP ${response.status})`;
  const requestId = errEnv?.error?.request_id;

  if (code === 'INVALID_SETTINGS') {
    const rawFieldErrors = errEnv.error.field_errors;
    const fieldErrors = Array.isArray(rawFieldErrors)
      ? (rawFieldErrors as SettingsFieldError[])
      : [];
    return { kind: 'invalid', message, fieldErrors, requestId };
  }
  if (code === 'SETTINGS_PERSIST_FAILED') {
    return { kind: 'persist_failed', message, requestId };
  }
  return { kind: 'unknown_error', message, code, httpStatus: response.status, requestId };
}

// ============== V1.0.4 F4：错误分类与中文文案 ==============

export type ErrorCategory =
  | 'network'
  | 'timeout'
  | 'rate_limited'
  | 'token_limit'
  | 'provider_unconfigured'
  | 'server_error'
  | 'interrupted'
  | 'ocr_text_unavailable'
  | 'unknown';

/** 把 catch 到的 err 归类到 ErrorCategory，仅用于 UI 文案分支。 */
export function classifyApiError(err: unknown): ErrorCategory {
  if (err instanceof TranslateApiError) {
    const code = err.code;
    if (code === 'OCR_TEXT_UNAVAILABLE') return 'ocr_text_unavailable';
    if (code === 'STREAM_INTERRUPTED') return 'interrupted';
    if (code === 'NETWORK_ERROR') return 'network';
    if (code === 'PROVIDER_ERROR' || code === 'PROVIDER_UNCONFIGURED') return 'provider_unconfigured';
    if (code === 'INVALID_RESPONSE') return 'server_error';
    const s = err.httpStatus ?? 0;
    if (s === 429) return 'rate_limited';
    if (s === 408 || s === 504) return 'timeout';
    if (s >= 500) return 'server_error';
    if (s >= 400) return 'server_error';
  }
  if (err instanceof Error) {
    const msg = err.message.toLowerCase();
    if (msg.includes('aborted') || msg.includes('timeout')) return 'timeout';
    if (msg.includes('fetch') || msg.includes('network')) return 'network';
    if (msg.includes('context length') || msg.includes('token')) return 'token_limit';
  }
  return 'unknown';
}

/** ErrorCategory → 中文文案；UI 用。 */
export function errorMessageFor(category: ErrorCategory): string {
  switch (category) {
    case 'network':
      return '网络异常或后端不可达，请检查网络与后端服务后重试。';
    case 'timeout':
      return '请求超时，可能是模型响应较慢或网络不稳，建议稍候重试。';
    case 'rate_limited':
      return '请求过于频繁（429），请稍候再试。';
    case 'token_limit':
      return '上下文长度超出模型上限，建议缩小选区或精简追问内容。';
    case 'provider_unconfigured':
      return 'AI 服务未就绪：可能是 API Key 未配置 / 已失效，请到「设置」检查。';
    case 'server_error':
      return '后端处理失败，请稍后重试；若持续出现请检查后端日志。';
    case 'interrupted':
      return '流式输出中断，可点击重试继续。';
    case 'ocr_text_unavailable':
      return '识别文本缺失，请重新截图发起新对话。';
    case 'unknown':
    default:
      return 'AI 调用失败，请重试。';
  }
}

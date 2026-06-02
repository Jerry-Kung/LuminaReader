const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export type TaskType = 'translate' | 'explain';

export interface TranslateSelection {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  dpi: number;
}

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

export interface RunResult {
  text: string;
  sessionId: string;
  turnIndex: number;
  meta: TranslateMeta;
}

export interface RunOptions {
  targetLang?: string;
  userQuestion?: string;
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

interface RunData {
  text: string;
  session_id: string;
  conversation_id?: string;
  meta: TranslateMeta & { turn_index?: number };
}

export class TranslateApiError extends Error {
  code: string;
  requestId?: string;
  httpStatus?: number;

  constructor(code: string, message: string, requestId?: string, httpStatus?: number) {
    super(message);
    this.code = code;
    this.requestId = requestId;
    this.httpStatus = httpStatus;
  }
}

const MOCK_TEXTS: Record<TaskType, string> = {
  translate:
    '这是模拟的翻译结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 翻译的实际内容。\n\n您可以框选 PDF 中的英文段落，点击 Run 按钮，AI 将为您把选区内容翻译为简体中文。',
  explain:
    '这是模拟的解释结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 对所选内容的深度解读，包括：核心观点、术语说明、必要的背景知识。',
};

const mockTurnCounter: Record<string, number> = {};

function mockRun(
  taskType: TaskType,
  sessionId: string,
  userQuestion?: string,
): Promise<RunResult> {
  return new Promise((resolve) => {
    const turnIndex = mockTurnCounter[sessionId] ?? 0;
    mockTurnCounter[sessionId] = turnIndex + 1;
    const baseText = turnIndex === 0 ? MOCK_TEXTS[taskType] : '这是模拟的追问回答。';
    const text = userQuestion ? `（针对你的问题：「${userQuestion}」）\n\n${baseText}` : baseText;
    setTimeout(
      () =>
        resolve({
          text,
          sessionId,
          turnIndex,
          meta: { model: 'mock', latency_ms: 0, task_type: taskType, turn_index: turnIndex },
        }),
      800 + Math.random() * 700,
    );
  });
}

async function postRun(body: Record<string, unknown>): Promise<RunResult> {
  const url = `${API_BASE}/api/v1/run`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }

  let envelope: Envelope<RunData>;
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

  if (envelope.ok === true) {
    const data = envelope.data;
    return {
      text: data.text,
      sessionId: data.session_id,
      turnIndex: data.meta?.turn_index ?? 0,
      meta: data.meta ?? {},
    };
  }

  const errorBody = envelope.error;
  throw new TranslateApiError(
    errorBody?.code || 'INTERNAL_ERROR',
    errorBody?.message || 'Unknown backend error.',
    errorBody?.request_id,
    response.status,
  );
}

// First turn: image + selection required; backend creates the session.
// V1.0.3: pdfId required so backend can resolve project context.
export async function runTask(
  taskType: TaskType,
  selection: TranslateSelection,
  image: TranslateImage,
  options: RunOptions = {},
): Promise<RunResult> {
  if (!API_BASE) {
    return mockRun(taskType, `mock-${Date.now()}`, options.userQuestion);
  }

  return postRun({
    task_type: taskType,
    session_id: null,
    pdf_id: options.pdfId ?? null,
    selection: {
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
    },
  });
}

// Follow-up turn: text-driven only (Scheme D). No image; backend holds extracted_text + history.
export async function runFollowUp(
  taskType: TaskType,
  sessionId: string,
  userQuestion: string,
  options: { targetLang?: string } = {},
): Promise<RunResult> {
  if (!API_BASE) {
    return mockRun(taskType, sessionId, userQuestion);
  }

  return postRun({
    task_type: taskType,
    session_id: sessionId,
    selection: null,
    image: null,
    options: {
      target_lang: options.targetLang ?? 'zh-CN',
      user_question: userQuestion,
    },
  });
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

// V1.0.4 F9: persist last_read_page. 204/404 both resolve; 400 throws.
export async function updateReadingPosition(
  pdfId: string,
  lastReadPage: number,
): Promise<void> {
  if (!API_BASE) return;
  if (!Number.isInteger(lastReadPage) || lastReadPage < 1) {
    throw new TranslateApiError(
      'INVALID_REQUEST',
      `last_read_page must be a positive integer (got ${lastReadPage}).`,
    );
  }
  const url = `${API_BASE}/api/v1/pdfs/${encodeURIComponent(pdfId)}/reading-position`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ last_read_page: lastReadPage }),
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

// V1.0.4 F3: 模型配置（设置页）
// 后端 settings API 尚未实现，本节为占位实现：API_BASE 为空时走内存 mock，
// 接通后端后只需把 fetch/解析改成 v1 信封契约（GET/PUT /api/v1/settings）。

export interface Settings {
  service_url: string;
  api_key: string;
  api_key_mask: string | null;
  default_model: string;
  timeout_seconds: number;
  ocr_model: string;
  translate_model: string;
  explain_model: string;
  config_source: 'environment' | 'local';
  is_ready: boolean;
}

export type SettingsForm = Omit<Settings, 'api_key_mask' | 'config_source' | 'is_ready'>;

const SETTINGS_MOCK_STATE: { current: Settings } = {
  current: {
    service_url: 'https://api.openai.com/v1',
    api_key: '',
    api_key_mask: null,
    default_model: 'gpt-4o',
    timeout_seconds: 60,
    ocr_model: '',
    translate_model: '',
    explain_model: '',
    config_source: 'environment',
    is_ready: false,
  },
};

function maskKey(key: string): string | null {
  if (!key) return null;
  const tail = key.slice(-4);
  return `sk-***...${tail}`;
}

export async function getSettings(): Promise<Settings> {
  if (!API_BASE) {
    return { ...SETTINGS_MOCK_STATE.current };
  }
  const url = `${API_BASE}/api/v1/settings`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    throw new TranslateApiError('NETWORK_ERROR', msg);
  }
  return parseEnvelope<Settings>(response);
}

export async function saveSettings(
  form: SettingsForm,
): Promise<{ success: boolean; error?: string }> {
  if (!API_BASE) {
    if (!form.service_url.startsWith('http://') && !form.service_url.startsWith('https://')) {
      return { success: false, error: '请输入合法的 http(s) 地址' };
    }
    if (form.timeout_seconds < 5 || form.timeout_seconds > 300) {
      return { success: false, error: '超时秒数应在 5 到 300 之间' };
    }
    if (!form.default_model.trim()) {
      return { success: false, error: '默认模型不能为空' };
    }
    SETTINGS_MOCK_STATE.current = {
      ...SETTINGS_MOCK_STATE.current,
      ...form,
      api_key_mask: maskKey(form.api_key),
      config_source: 'local',
      is_ready: !!form.api_key,
    };
    return { success: true };
  }
  const url = `${API_BASE}/api/v1/settings`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Failed to reach backend.';
    return { success: false, error: msg };
  }
  if (response.ok) return { success: true };
  let envelope: ErrorEnvelope | null = null;
  try {
    envelope = await response.json();
  } catch {
    envelope = null;
  }
  return {
    success: false,
    error: envelope?.error?.message || `保存失败 (HTTP ${response.status})`,
  };
}

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

export interface SettingsSource {
  provider: SettingsProvider;
  task_models: SettingsTaskModels;
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
  | 'unknown';

/** 把 catch 到的 err 归类到 ErrorCategory，仅用于 UI 文案分支。 */
export function classifyApiError(err: unknown): ErrorCategory {
  if (err instanceof TranslateApiError) {
    const code = err.code;
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
    case 'unknown':
    default:
      return 'AI 调用失败，请重试。';
  }
}

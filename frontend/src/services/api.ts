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
  };
}

type Envelope<T> = SuccessEnvelope<T> | ErrorEnvelope;

interface RunData {
  text: string;
  session_id: string;
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

let mockTurnCounter: Record<string, number> = {};

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
  } catch (err: any) {
    throw new TranslateApiError('NETWORK_ERROR', err?.message || 'Failed to reach backend.');
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

// First turn: image + selection required; optional user_question; backend creates the session.
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
    selection: {
      pdf_id: null,
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
  } catch (err: any) {
    throw new TranslateApiError('NETWORK_ERROR', err?.message || 'Failed to reach backend.');
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

// v0 compatibility wrapper — delegates to runTask (first turn). Kept per design.
export async function translateSelection(
  selection: TranslateSelection,
  image: TranslateImage,
  options: { targetLang?: string; taskType?: TaskType; userQuestion?: string } = {},
): Promise<RunResult> {
  return runTask(options.taskType ?? 'translate', selection, image, {
    targetLang: options.targetLang,
    userQuestion: options.userQuestion,
  });
}

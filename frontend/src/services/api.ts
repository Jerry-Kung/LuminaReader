const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

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
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

export interface TranslateResult {
  text: string;
  meta: TranslateMeta;
}

export interface TranslateOptions {
  targetLang?: string;
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

function mockTranslate(): Promise<TranslateResult> {
  const text =
    '这是模拟的翻译结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 翻译的实际内容。\n\n您可以框选 PDF 中的英文段落，点击翻译按钮，AI 将为您把选区内容翻译为简体中文。';

  return new Promise((resolve) => {
    setTimeout(
      () =>
        resolve({
          text,
          meta: { model: 'mock', latency_ms: 0 },
        }),
      800 + Math.random() * 700,
    );
  });
}

export async function translateSelection(
  selection: TranslateSelection,
  image: TranslateImage,
  options: TranslateOptions = {},
): Promise<TranslateResult> {
  if (!API_BASE) {
    return mockTranslate();
  }

  const url = `${API_BASE}/api/v0/translate`;

  const body = {
    task_type: 'translate',
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
    },
  };

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err: any) {
    throw new TranslateApiError(
      'NETWORK_ERROR',
      err?.message || 'Failed to reach backend.',
    );
  }

  let envelope: Envelope<TranslateResult>;
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

  if (envelope.ok) {
    return envelope.data;
  }

  throw new TranslateApiError(
    envelope.error?.code || 'INTERNAL_ERROR',
    envelope.error?.message || 'Unknown backend error.',
    envelope.error?.request_id,
    response.status,
  );
}

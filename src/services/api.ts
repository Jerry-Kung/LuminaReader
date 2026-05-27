const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface TranslateRequest {
  image: string;
  target_language: string;
}

interface TranslateResponse {
  translated_text: string;
}

function mockTranslate(targetLanguage: string): Promise<TranslateResponse> {
  const mockTexts: Record<string, string> = {
    'zh-CN': '这是模拟的翻译结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 翻译的实际内容。\n\n您可以框选 PDF 中的英文段落，点击翻译按钮，AI 将为您把选区内容翻译为简体中文。',
  };

  const text = mockTexts[targetLanguage] || mockTexts['zh-CN'];

  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ translated_text: text });
    }, 800 + Math.random() * 700);
  });
}

export async function translateSelection(
  imageBase64: string,
  targetLanguage: string = 'zh-CN',
): Promise<TranslateResponse> {
  if (!API_BASE) {
    return mockTranslate(targetLanguage);
  }

  const url = `${API_BASE}/api/translate`;

  const body: TranslateRequest = {
    image: imageBase64,
    target_language: targetLanguage,
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error');
    throw new Error(`Translation failed (${response.status}): ${errorText}`);
  }

  return response.json();
}
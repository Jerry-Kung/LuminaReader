const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface AIRequest {
  image: string;
  target_language: string;
  task_type: 'translate' | 'explain';
}

interface AIResponse {
  translated_text: string;
}

function mockAI(
  taskType: 'translate' | 'explain',
  targetLanguage: string,
): Promise<AIResponse> {
  const mockTexts: Record<string, Record<string, string>> = {
    translate: {
      'zh-CN':
        '这是模拟的翻译结果。\n\n当您配置了后端 API 地址后（在 .env 文件中设置 VITE_API_BASE_URL），这里将显示 AI 翻译的实际内容。\n\n您可以框选 PDF 中的英文段落，点击翻译按钮，AI 将为您把选区内容翻译为简体中文。',
    },
    explain: {
      'zh-CN':
        '这是模拟的解释结果。\n\n所选内容似乎是一段说明性文字，主要介绍了系统的使用方法。当您配置后端 API 后，AI 将对您选中的 PDF 内容进行深度解读，包括：核心观点提炼、逻辑结构分析、背景知识补充等。',
    },
  };

  const text =
    mockTexts[taskType]?.[targetLanguage] ||
    mockTexts[taskType]?.['zh-CN'] ||
    mockTexts.translate['zh-CN'];

  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ translated_text: text });
    }, 800 + Math.random() * 700);
  });
}

export async function translateSelection(
  imageBase64: string,
  targetLanguage: string = 'zh-CN',
  taskType: 'translate' | 'explain' = 'translate',
): Promise<AIResponse> {
  if (!API_BASE) {
    return mockAI(taskType, targetLanguage);
  }

  const url = `${API_BASE}/api/translate`;

  const body: AIRequest = {
    image: imageBase64,
    target_language: targetLanguage,
    task_type: taskType,
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
    throw new Error(`AI request failed (${response.status}): ${errorText}`);
  }

  return response.json();
}
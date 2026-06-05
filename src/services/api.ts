const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export type TaskType = 'translate' | 'explain' | 'dictionary' | 'chat';

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface HistoryMessage {
  id: number;
  role: 'user' | 'ai';
  text: string;
  timestamp: number;
  isLoading?: boolean;
  isError?: boolean;
  errorText?: string;
}

export interface HistoryConversation {
  id: number;
  book_id: string;
  type: TaskType;
  thumbnail: string;
  first_question: string;
  created_at: string;
  updated_at: string;
  messages: HistoryMessage[];
}

export interface Book {
  id: string;
  title: string;
  file_name: string;
  file_size: number;
  cover_url: string;
  created_at: string;
  updated_at: string;
  page_count: number;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

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

interface AIRequest {
  image: string;
  target_language: string;
  task_type: TaskType;
  user_message?: string;
  conversation_history?: ConversationMessage[];
}

interface AIResponse {
  translated_text: string;
}

const MOCK_TRANSLATE = `以下是对所选内容的翻译结果：

这段文字的核心论点是**欧拉公式**（Euler\'s Formula），它建立了顶点数、边数与面数之间的基本关系：

$$V - E + F = 2$$

其中：
- $V$ 代表图形的**顶点数**（Vertices）
- $E$ 代表图形的**边数**（Edges）
- $F$ 代表图形的**面数**（Faces），包括外部无界面

这一公式适用于所有**平面图**和**凸多面体**，是拓扑学与图论中的经典定理。`;

const MOCK_EXPLAIN = `### 内容解析

这段内容涉及**图论**（Graph Theory）中的一个基础定理。

#### 主要概念

1. **平面图**：可以画在平面上且边不交叉的图
2. **连通图**：任意两点之间存在路径的图
3. **欧拉公式**：对任意连通平面图，有

$$V - E + F = 2$$

#### 推导思路

> 从单个顶点出发，通过数学归纳法，每次增加一条边时分析 $V$、$E$、$F$ 的变化量，可以证明它们的差值始终保持为 2。

这一结论的意义在于，无论图的形状多么复杂，这三个量之间的约束关系**永远不变**。`;

const MOCK_DICTIONARY = `### isomorphism 同构

**发音**: /ˌaɪsəˈmɔːrfɪzəm/

**词性**: 名词

**释义**:

1. **（数学）** 两个同类型代数结构之间的双射且保持结构的映射。若群 $G$ 与 $H$ 之间存在同构映射，则称 $G$ 与 $H$ 同构，记作 $G \cong H$。

2. **（生物学）** 不同物种生物体之间在形态或结构上的相似性。

**词源**: 希腊语 *isos*（相等的）+ *morphe*（形态）

**例句**: 恒等映射 $\text{id}: G \to G$ 是一个平凡的同构。`;

const MOCK_CHAT = `当然！这段内容讨论了一个非常重要的拓扑学概念：**紧致性**（Compactness）。

### 直观理解

想象一个**闭区间** $[0, 1]$：无论你如何用无限多个小开区间去覆盖它，你总能从中挑出**有限个**来完成任务。这就是紧致性的本质——"无限覆盖必有有限子覆盖"。

### 为什么重要

紧致空间在许多方面表现得像**有限集合**：
- 紧致集合上的连续函数一定有界，并能取到最大值和最小值
- 紧致空间上的连续函数一定是**一致连续**的

这使其成为分析和拓扑中最重要的性质之一。`;

const MOCK_FOLLOWUP_TRANSLATE = [
  `**追问回答**：这是一个很好的问题。\n\n您提到的这个词在上下文中指的是"映射"（Mapping）——一种将一个集合的元素对应到另一个集合的规则。\n\n在翻译领域，它特指\`one-to-one correspondence\`，即**一一对应**关系。`,
  `**深入解释**：这一步推导的关键在于，每增加一条边时有两种情况：\n\n- 若连接两个已有顶点：$E+1$，$F+1$，$V$ 不变\n- 若引入新顶点：$E+1$，$V+1$，$F$ 不变\n\n两种情况下 $V - E + F$ 的值都不变，证明完毕。`,
];

let followupIndex = 0;

function mockAI(
  taskType: TaskType,
  userMessage?: string,
): Promise<AIResponse> {
  let text: string;

  if (userMessage && userMessage.trim().length > 0) {
    text = MOCK_FOLLOWUP_TRANSLATE[followupIndex % MOCK_FOLLOWUP_TRANSLATE.length];
    followupIndex += 1;
  } else if (taskType === 'explain') {
    text = MOCK_EXPLAIN;
  } else if (taskType === 'dictionary') {
    text = MOCK_DICTIONARY;
  } else if (taskType === 'chat') {
    text = MOCK_CHAT;
  } else {
    text = MOCK_TRANSLATE;
  }

  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({ translated_text: text });
    }, 800 + Math.random() * 600);
  });
}

export async function translateSelection(
  imageBase64: string,
  targetLanguage: string = 'zh-CN',
  taskType: TaskType = 'translate',
  userMessage?: string,
  conversationHistory?: ConversationMessage[],
): Promise<AIResponse> {
  if (!API_BASE) {
    return mockAI(taskType, userMessage);
  }

  const url = `${API_BASE}/api/translate`;

  const body: AIRequest = {
    image: imageBase64,
    target_language: targetLanguage,
    task_type: taskType,
    ...(userMessage ? { user_message: userMessage } : {}),
    ...(conversationHistory && conversationHistory.length > 0
      ? { conversation_history: conversationHistory }
      : {}),
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

// Bookshelf API

export async function listBooks(): Promise<Book[]> {
  if (!API_BASE) {
    const { fetchBooks } = await import('@/mocks/bookshelf');
    return fetchBooks();
  }

  const response = await fetch(`${API_BASE}/api/books`);
  if (!response.ok) {
    throw new Error(`Failed to fetch books (${response.status})`);
  }
  return response.json();
}

export async function getBook(id: string): Promise<Book | null> {
  if (!API_BASE) {
    const { fetchBookById } = await import('@/mocks/bookshelf');
    return fetchBookById(id);
  }

  const response = await fetch(`${API_BASE}/api/books/${id}`);
  if (!response.ok) {
    if (response.status === 404) return null;
    throw new Error(`Failed to fetch book (${response.status})`);
  }
  return response.json();
}

export async function uploadBook(
  file: File,
  onProgress?: (progress: UploadProgress) => void,
  forceNew?: boolean,
): Promise<{ book: Book; isDuplicate: false } | { existingBook: Book; isDuplicate: true }> {
  if (!API_BASE) {
    const { simulateUpload } = await import('@/mocks/bookshelf');
    return simulateUpload(file, onProgress || (() => {}), forceNew);
  }

  const formData = new FormData();
  formData.append('file', file);
  if (forceNew) {
    formData.append('force_new', 'true');
  }

  // For real API with progress, we'd use XMLHttpRequest
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress({
          loaded: e.loaded,
          total: e.total,
          percentage: Math.round((e.loaded / e.total) * 100),
        });
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status === 200 || xhr.status === 201) {
        resolve(JSON.parse(xhr.responseText));
      } else if (xhr.status === 409) {
        const data = JSON.parse(xhr.responseText);
        resolve({ existingBook: data.existing_book, isDuplicate: true });
      } else {
        reject(new Error(`Upload failed (${xhr.status}): ${xhr.statusText}`));
      }
    });

    xhr.addEventListener('error', () => reject(new Error('Upload failed')));
    xhr.open('POST', `${API_BASE}/api/books/upload`);
    xhr.send(formData);
  });
}

export async function deleteBook(id: string): Promise<void> {
  if (!API_BASE) {
    const { deleteBookById } = await import('@/mocks/bookshelf');
    return deleteBookById(id);
  }

  const response = await fetch(`${API_BASE}/api/books/${id}`, {
    method: 'DELETE',
  });
  if (!response.ok) {
    throw new Error(`Failed to delete book (${response.status})`);
  }
}

export async function listHistoryConversations(bookId: string): Promise<HistoryConversation[]> {
  if (!API_BASE) {
    const { fetchHistoryConversations } = await import('@/mocks/history');
    return fetchHistoryConversations(bookId);
  }

  const response = await fetch(`${API_BASE}/api/books/${bookId}/history`);
  if (!response.ok) {
    throw new Error(`Failed to fetch history (${response.status})`);
  }
  return response.json();
}

export async function getHistoryConversation(id: number): Promise<HistoryConversation | null> {
  if (!API_BASE) {
    const { fetchHistoryConversationById } = await import('@/mocks/history');
    return fetchHistoryConversationById(id);
  }

  const response = await fetch(`${API_BASE}/api/history/${id}`);
  if (!response.ok) {
    if (response.status === 404) return null;
    throw new Error(`Failed to fetch history conversation (${response.status})`);
  }
  return response.json();
}

// Settings API

export async function getSettings(): Promise<Settings> {
  if (!API_BASE) {
    const { fetchSettings } = await import('@/mocks/settings');
    return fetchSettings();
  }

  const response = await fetch(`${API_BASE}/api/settings`);
  if (!response.ok) {
    throw new Error(`Failed to fetch settings (${response.status})`);
  }
  return response.json();
}

export async function saveSettings(
  settings: Omit<Settings, 'api_key_mask' | 'config_source' | 'is_ready'>,
): Promise<{ success: boolean; error?: string }> {
  if (!API_BASE) {
    const { saveSettingsToMock } = await import('@/mocks/settings');
    return saveSettingsToMock(settings);
  }

  const response = await fetch(`${API_BASE}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    const errorText = await response.text().catch(() => 'Unknown error');
    return { success: false, error: errorText };
  }

  const result = await response.json();
  return { success: true };
}
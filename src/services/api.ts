const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export type TaskType = 'translate' | 'explain';

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
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
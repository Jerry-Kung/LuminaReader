import type { HistoryConversation } from '@/services/api';

const svgToDataUrl = (fill: string, label: string) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="160"><rect width="200" height="160" fill="${fill}"/><text x="100" y="55" text-anchor="middle" fill="#8b7355" font-size="11" font-family="sans-serif">Page 14</text><rect x="30" y="75" width="140" height="6" rx="2" fill="#b8a890" opacity="0.4"/><rect x="30" y="88" width="110" height="6" rx="2" fill="#b8a890" opacity="0.3"/><rect x="30" y="101" width="125" height="6" rx="2" fill="#b8a890" opacity="0.4"/><rect x="30" y="114" width="90" height="6" rx="2" fill="#b8a890" opacity="0.3"/><rect x="30" y="127" width="120" height="6" rx="2" fill="#b8a890" opacity="0.4"/></svg>`;
  return `data:image/svg+xml;base64,${btoa(svg)}`;
};

const thumbs = [
  svgToDataUrl('#f5f5e4', 'A'),
  svgToDataUrl('#faf8f3', 'B'),
  svgToDataUrl('#f0ebe3', 'C'),
  svgToDataUrl('#e8e4da', 'D'),
  svgToDataUrl('#ddd5c5', 'E'),
  svgToDataUrl('#d5cdc0', 'F'),
  svgToDataUrl('#e0d8c8', 'G'),
  svgToDataUrl('#d8d0c0', 'H'),
];

function ago(hours: number): string {
  const d = new Date();
  d.setHours(d.getHours() - hours);
  return d.toISOString();
}

export const mockHistory: HistoryConversation[] = [
  {
    id: 101,
    book_id: 'book-001',
    type: 'translate',
    thumbnail: thumbs[0],
    first_question: 'Translate this paragraph about graph connectivity',
    created_at: ago(2),
    updated_at: ago(2),
    messages: [
      {
        id: 1001,
        role: 'user',
        text: 'Translate this paragraph about graph connectivity',
        timestamp: new Date(ago(2)).getTime(),
      },
      {
        id: 1002,
        role: 'ai',
        text: '**Graph Connectivity**\n\nA graph is said to be **connected** if there is a path between every pair of vertices. In a connected graph, no vertex is isolated.\n\nThe study of connectivity is fundamental in network analysis, as it determines whether information can flow between all nodes in a system.',
        timestamp: new Date(ago(2)).getTime() + 2000,
      },
    ],
  },
  {
    id: 102,
    book_id: 'book-001',
    type: 'explain',
    thumbnail: thumbs[1],
    first_question: 'Explain what Euler\'s formula means in this context',
    created_at: ago(8),
    updated_at: ago(5),
    messages: [
      {
        id: 1003,
        role: 'user',
        text: 'Explain what Euler\'s formula means in this context',
        timestamp: new Date(ago(8)).getTime(),
      },
      {
        id: 1004,
        role: 'ai',
        text: '### Euler\'s Formula for Planar Graphs\n\nFor any connected planar graph, the following relationship always holds:\n\n$$V - E + F = 2$$\n\nWhere:\n- $V$ = number of vertices\n- $E$ = number of edges\n- $F$ = number of faces (including the outer face)\n\nThis invariant is the cornerstone of topological graph theory. It tells us that the **structure** of the graph, not its geometric shape, determines this numerical relationship.',
        timestamp: new Date(ago(8)).getTime() + 3000,
      },
      {
        id: 1005,
        role: 'user',
        text: 'Does this apply to non-planar graphs too?',
        timestamp: new Date(ago(5)).getTime(),
      },
      {
        id: 1006,
        role: 'ai',
        text: 'No, Euler\'s formula in this form **only applies to planar graphs** and polyhedra.\n\nFor non-planar graphs, the relationship changes. The generalization is the **Euler characteristic** $\chi = V - E + F$, which depends on the surface the graph is embedded on:\n\n| Surface | $\chi$ |\n|---------|--------|\n| Sphere / Plane | 2 |\n| Torus | 0 |\n| Double torus | -2 |\n\nSo for a graph drawn on a torus, $V - E + F = 0$.',
        timestamp: new Date(ago(5)).getTime() + 2500,
      },
    ],
  },
  {
    id: 103,
    book_id: 'book-001',
    type: 'translate',
    thumbnail: thumbs[2],
    first_question: 'Translate this theorem statement',
    created_at: ago(24),
    updated_at: ago(24),
    messages: [
      {
        id: 1007,
        role: 'user',
        text: 'Translate this theorem statement',
        timestamp: new Date(ago(24)).getTime(),
      },
      {
        id: 1008,
        role: 'ai',
        text: '**Theorem 3.4 (Menger, 1927).**\n\nLet $G$ be a graph and $u, v$ two distinct vertices. The minimum number of vertices whose removal disconnects $u$ and $v$ equals the maximum number of internally disjoint $u-v$ paths.\n\nThis is one of the most fundamental results in connectivity theory.',
        timestamp: new Date(ago(24)).getTime() + 2000,
      },
    ],
  },
  {
    id: 104,
    book_id: 'book-002',
    type: 'explain',
    thumbnail: thumbs[3],
    first_question: 'What is a manifold in simple terms?',
    created_at: ago(12),
    updated_at: ago(10),
    messages: [
      {
        id: 1009,
        role: 'user',
        text: 'What is a manifold in simple terms?',
        timestamp: new Date(ago(12)).getTime(),
      },
      {
        id: 1010,
        role: 'ai',
        text: 'A **manifold** is a space that locally looks like Euclidean space.\n\nThink of it this way:\n\n1. The **surface of the Earth** is a 2-dimensional manifold — it looks flat when you stand in one spot, but globally it\'s a sphere.\n2. A **circle** is a 1-dimensional manifold — zoom in close enough and it looks like a straight line.\n\nFormally, an $n$-dimensional manifold is a topological space where every point has a neighborhood homeomorphic to $\mathbb{R}^n$.',
        timestamp: new Date(ago(12)).getTime() + 2500,
      },
      {
        id: 1011,
        role: 'user',
        text: 'So a donut is also a manifold?',
        timestamp: new Date(ago(10)).getTime(),
      },
      {
        id: 1012,
        role: 'ai',
        text: 'Yes! A **torus** (donut shape) is a 2-dimensional manifold.\n\nIn fact, it\'s one of the simplest non-trivial 2-manifolds. Unlike a sphere, a torus has a **hole**, which gives it interesting topological properties:\n\n- Its **genus** is 1 (one hole)\n- Its **Euler characteristic** is $\chi = 0$\n- It can be described as $\mathbb{S}^1 \times \mathbb{S}^1$ (a product of two circles)',
        timestamp: new Date(ago(10)).getTime() + 2000,
      },
    ],
  },
  {
    id: 105,
    book_id: 'book-003',
    type: 'translate',
    thumbnail: thumbs[4],
    first_question: 'Translate this section about eigenvalues',
    created_at: ago(48),
    updated_at: ago(48),
    messages: [
      {
        id: 1013,
        role: 'user',
        text: 'Translate this section about eigenvalues',
        timestamp: new Date(ago(48)).getTime(),
      },
      {
        id: 1014,
        role: 'ai',
        text: '**Eigenvalues and Eigenvectors**\n\nFor a square matrix $A$, a non-zero vector $v$ is called an **eigenvector** if:\n\n$$Av = \\lambda v$$\n\nwhere $\lambda$ is the corresponding **eigenvalue**.\n\nEigenvalues reveal the fundamental scaling behavior of a linear transformation. They are crucial in:\n\n- Stability analysis of dynamical systems\n- Principal Component Analysis (PCA)\n- Quantum mechanics (energy levels)\n- Vibration analysis of mechanical structures',
        timestamp: new Date(ago(48)).getTime() + 2000,
      },
    ],
  },
];

export async function fetchHistoryConversations(bookId: string): Promise<HistoryConversation[]> {
  await new Promise((resolve) => setTimeout(resolve, 300));
  return mockHistory.filter((h) => h.book_id === bookId);
}

export async function fetchHistoryConversationById(id: number): Promise<HistoryConversation | null> {
  await new Promise((resolve) => setTimeout(resolve, 200));
  return mockHistory.find((h) => h.id === id) || null;
}
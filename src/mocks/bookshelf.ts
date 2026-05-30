import type { Book, UploadProgress } from '@/services/api';

export const mockBooks: Book[] = [
  {
    id: 'book-001',
    title: 'Graph Theory - A Modern Approach',
    file_name: 'Graph Theory - A Modern Approach.pdf',
    file_size: 4_230_000,
    cover_url: '',
    created_at: '2026-05-28T10:30:00Z',
    updated_at: '2026-05-30T14:32:00Z',
    page_count: 312,
  },
  {
    id: 'book-002',
    title: 'Topology and Geometry for Physicists',
    file_name: 'Topology and Geometry for Physicists.pdf',
    file_size: 8_150_000,
    cover_url: '',
    created_at: '2026-05-25T09:15:00Z',
    updated_at: '2026-05-29T20:18:00Z',
    page_count: 489,
  },
  {
    id: 'book-003',
    title: 'Introduction to Linear Algebra',
    file_name: 'Introduction to Linear Algebra.pdf',
    file_size: 2_840_000,
    cover_url: '',
    created_at: '2026-05-20T16:45:00Z',
    updated_at: '2026-05-27T11:22:00Z',
    page_count: 215,
  },
  {
    id: 'book-004',
    title: 'Deep Learning with PyTorch',
    file_name: 'Deep Learning with PyTorch.pdf',
    file_size: 12_600_000,
    cover_url: '',
    created_at: '2026-05-18T08:00:00Z',
    updated_at: '2026-05-26T09:50:00Z',
    page_count: 567,
  },
  {
    id: 'book-005',
    title: 'The Elements of Statistical Learning',
    file_name: 'The Elements of Statistical Learning.pdf',
    file_size: 15_200_000,
    cover_url: '',
    created_at: '2026-05-15T13:20:00Z',
    updated_at: '2026-05-22T16:40:00Z',
    page_count: 745,
  },
  {
    id: 'book-006',
    title: 'Concrete Mathematics',
    file_name: 'Concrete Mathematics.pdf',
    file_size: 6_780_000,
    cover_url: '',
    created_at: '2026-05-10T11:10:00Z',
    updated_at: '2026-05-19T10:15:00Z',
    page_count: 672,
  },
];

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimeAgo(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;
  if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} week${Math.floor(diffDays / 7) > 1 ? 's' : ''} ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function generateCoverColor(title: string): string {
  const palette = [
    '#e8d5b7', '#d4c5a9', '#c9b99a', '#d5c4b0',
    '#e0d0b8', '#d8c8a8', '#cdc0b0', '#d6ccb0',
    '#c5b8a0', '#d0c0a8', '#b8a890', '#c8b8a0',
    '#a89880', '#b8a888', '#d0c8b8', '#c8b8a8',
  ];
  let hash = 0;
  for (let i = 0; i < title.length; i++) {
    hash = ((hash << 5) - hash) + title.charCodeAt(i);
    hash |= 0;
  }
  return palette[Math.abs(hash) % palette.length];
}

export function generateCoverPattern(title: string): string {
  const patterns = [
    'radial-gradient(circle at 30% 30%, rgba(255,255,255,0.15) 0%, transparent 50%)',
    'linear-gradient(135deg, rgba(255,255,255,0.1) 0%, transparent 50%)',
    'radial-gradient(circle at 70% 70%, rgba(255,255,255,0.12) 0%, transparent 40%)',
    'linear-gradient(45deg, rgba(255,255,255,0.08) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.08) 75%, transparent 75%, transparent)',
    'radial-gradient(ellipse at 50% 100%, rgba(255,255,255,0.1) 0%, transparent 60%)',
    'linear-gradient(180deg, rgba(255,255,255,0.05) 0%, transparent 40%)',
  ];
  let hash = 0;
  for (let i = 0; i < title.length; i++) {
    hash = ((hash << 5) - hash) + title.charCodeAt(i);
    hash |= 0;
  }
  return patterns[Math.abs(hash) % patterns.length];
}

export async function simulateUpload(
  file: File,
  onProgress: (progress: UploadProgress) => void,
  forceNew?: boolean,
): Promise<{ book: Book; isDuplicate: false } | { existingBook: Book; isDuplicate: true }> {
  const totalSize = file.size;

  // Check for duplicate (mock logic)
  if (!forceNew) {
    const duplicate = mockBooks.find((b) => b.title === file.name.replace(/\.pdf$/i, '') && b.file_size === file.size);
    if (duplicate) {
      await delay(800);
      return { existingBook: duplicate, isDuplicate: true };
    }
  }

  // Simulate upload progress
  const steps = 8;
  for (let i = 1; i <= steps; i++) {
    await delay(200 + Math.random() * 300);
    onProgress({
      loaded: Math.round((totalSize * i) / steps),
      total: totalSize,
      percentage: Math.round((i / steps) * 100),
    });
  }

  const newBook: Book = {
    id: `book-${Date.now()}`,
    title: file.name.replace(/\.pdf$/i, ''),
    file_name: file.name,
    file_size: file.size,
    cover_url: '',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    page_count: Math.floor(100 + Math.random() * 600),
  };

  // Prepend to mock storage
  mockBooks.unshift(newBook);

  return { book: newBook, isDuplicate: false };
}

export async function fetchBooks(): Promise<Book[]> {
  await delay(400);
  return [...mockBooks];
}

export async function fetchBookById(id: string): Promise<Book | null> {
  await delay(200);
  return mockBooks.find((b) => b.id === id) || null;
}

export async function deleteBookById(id: string): Promise<void> {
  await delay(300);
  const idx = mockBooks.findIndex((b) => b.id === id);
  if (idx !== -1) {
    mockBooks.splice(idx, 1);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
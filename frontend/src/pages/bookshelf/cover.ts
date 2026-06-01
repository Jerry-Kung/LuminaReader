// Placeholder cover utilities for book cards.
// Derives a deterministic color + diagonal-stripe pattern from a book name,
// and formats file sizes and "time ago" labels for V1.0.3 bookshelf cards.

const COVER_PALETTE = [
  '#fde68a', '#fcd34d', '#fbbf24',
  '#fed7aa', '#fdba74', '#fb923c',
  '#fecaca', '#fca5a5', '#f87171',
  '#bbf7d0', '#86efac', '#4ade80',
  '#a7f3d0', '#6ee7b7', '#34d399',
  '#bfdbfe', '#93c5fd', '#60a5fa',
  '#ddd6fe', '#c4b5fd', '#a78bfa',
  '#fbcfe8', '#f9a8d4', '#f472b6',
];

function hashString(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export function generateCoverColor(name: string): string {
  if (!name) return COVER_PALETTE[0];
  return COVER_PALETTE[hashString(name) % COVER_PALETTE.length];
}

export function generateCoverPattern(name: string): string {
  const h = hashString(name);
  const angle = (h % 6) * 30; // 0/30/60/90/120/150 deg
  const opacity = 0.06 + ((h >> 4) % 5) * 0.01; // 0.06 ~ 0.10
  return `repeating-linear-gradient(${angle}deg, transparent 0 12px, rgba(0,0,0,${opacity}) 12px 13px)`;
}

export function formatFileSize(bytes: number): string {
  if (!bytes || bytes <= 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

// Accepts epoch seconds (V1.0.3 backend uses int seconds).
export function formatTimeAgo(epochSeconds: number): string {
  if (!epochSeconds) return '刚刚上传';
  const nowSec = Math.floor(Date.now() / 1000);
  const diff = Math.max(0, nowSec - epochSeconds);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 2) return '昨天';
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400 / 7)} 周前`;
  return `${Math.floor(diff / 86400 / 30)} 个月前`;
}

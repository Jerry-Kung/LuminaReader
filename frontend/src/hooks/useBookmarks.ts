import { useCallback, useEffect, useState } from 'react';
import {
  createBookmark,
  deleteBookmark,
  listBookmarks,
  renameBookmark,
  type BookmarkItem,
} from '../services/api';

/** V1.2.2：书签 CRUD；列表始终按后端排序（page, offset_ratio）本地维护。 */
export function useBookmarks(pdfId: string | undefined) {
  const [bookmarks, setBookmarks] = useState<BookmarkItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setBookmarks([]);
    if (!pdfId) return;
    let cancelled = false;
    setLoading(true);
    listBookmarks(pdfId)
      .then((items) => {
        if (!cancelled) setBookmarks(items);
      })
      .catch(() => {
        /* MAY 档数据，加载失败静默为空列表 */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pdfId]);

  const sortInsert = (items: BookmarkItem[]) =>
    [...items].sort((a, b) => a.page - b.page || a.offset_ratio - b.offset_ratio);

  const add = useCallback(
    async (page: number, offsetRatio: number): Promise<BookmarkItem | null> => {
      if (!pdfId) return null;
      const created = await createBookmark(pdfId, {
        page,
        offset_ratio: Math.max(0, Math.min(1, offsetRatio)),
      });
      setBookmarks((prev) => sortInsert([...prev, created]));
      return created;
    },
    [pdfId],
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      if (!pdfId) return;
      await renameBookmark(pdfId, id, name);
      setBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, name } : b)));
    },
    [pdfId],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!pdfId) return;
      await deleteBookmark(pdfId, id);
      setBookmarks((prev) => prev.filter((b) => b.id !== id));
    },
    [pdfId],
  );

  return { bookmarks, loading, add, rename, remove };
}

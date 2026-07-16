import { useCallback, useEffect, useRef, useState } from 'react';
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
  const generationRef = useRef(0);

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    setBookmarks([]);
    if (!pdfId) return;
    setLoading(true);
    listBookmarks(pdfId)
      .then((items) => {
        if (generationRef.current === generation) setBookmarks(items);
      })
      .catch(() => {
        /* MAY 档数据，加载失败静默为空列表 */
      })
      .finally(() => {
        if (generationRef.current === generation) setLoading(false);
      });
  }, [pdfId]);

  const sortInsert = (items: BookmarkItem[]) =>
    [...items].sort((a, b) => a.page - b.page || a.offset_ratio - b.offset_ratio);

  const add = useCallback(
    async (page: number, offsetRatio: number): Promise<BookmarkItem | null> => {
      if (!pdfId) return null;
      const generation = generationRef.current;
      const created = await createBookmark(pdfId, {
        page,
        offset_ratio: Math.max(0, Math.min(1, offsetRatio)),
      });
      if (generationRef.current !== generation) return created;
      setBookmarks((prev) => sortInsert([...prev, created]));
      return created;
    },
    [pdfId],
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      if (!pdfId) return;
      const generation = generationRef.current;
      await renameBookmark(pdfId, id, name);
      if (generationRef.current !== generation) return;
      setBookmarks((prev) => prev.map((b) => (b.id === id ? { ...b, name } : b)));
    },
    [pdfId],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!pdfId) return;
      const generation = generationRef.current;
      await deleteBookmark(pdfId, id);
      if (generationRef.current !== generation) return;
      setBookmarks((prev) => prev.filter((b) => b.id !== id));
    },
    [pdfId],
  );

  return { bookmarks, loading, add, rename, remove };
}

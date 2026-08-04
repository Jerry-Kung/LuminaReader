import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createNote,
  deleteNote,
  listNotes,
  updateNote,
  type NoteCreateInput,
  type NoteItem,
} from '../services/api';

/** V1.2.5：笔记 CRUD；列表按后端排序（page, offset_ratio NULL 最前, created_at）本地维护。 */
export function useNotes(pdfId: string | undefined) {
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [loading, setLoading] = useState(false);
  const generationRef = useRef(0);

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    setNotes([]);
    if (!pdfId) return;
    setLoading(true);
    listNotes(pdfId)
      .then((items) => {
        if (generationRef.current === generation) setNotes(items);
      })
      .catch(() => {
        /* MAY 档数据，加载失败静默为空列表 */
      })
      .finally(() => {
        if (generationRef.current === generation) setLoading(false);
      });
  }, [pdfId]);

  // NULL offset_ratio 排同页最前，与后端 SQLite ASC 排序对齐
  const sortInsert = (items: NoteItem[]) =>
    [...items].sort(
      (a, b) =>
        a.page - b.page ||
        (a.offset_ratio ?? -1) - (b.offset_ratio ?? -1) ||
        a.created_at - b.created_at,
    );

  const add = useCallback(
    async (input: NoteCreateInput): Promise<NoteItem | null> => {
      if (!pdfId) return null;
      const generation = generationRef.current;
      const created = await createNote(pdfId, input);
      if (generationRef.current !== generation) return created;
      setNotes((prev) => sortInsert([...prev, created]));
      return created;
    },
    [pdfId],
  );

  const update = useCallback(
    async (id: string, patch: { content?: string; title?: string }) => {
      if (!pdfId) return;
      const generation = generationRef.current;
      const { updated_at } = await updateNote(pdfId, id, patch);
      if (generationRef.current !== generation) return;
      setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch, updated_at } : n)));
    },
    [pdfId],
  );

  const remove = useCallback(
    async (id: string) => {
      if (!pdfId) return;
      const generation = generationRef.current;
      await deleteNote(pdfId, id);
      if (generationRef.current !== generation) return;
      setNotes((prev) => prev.filter((n) => n.id !== id));
    },
    [pdfId],
  );

  return { notes, loading, add, update, remove };
}

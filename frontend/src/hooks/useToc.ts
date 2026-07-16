import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getToc,
  getTocLlmEstimate,
  recognizeToc,
  recognizeTocWithLlm,
  type TocInfo,
  type TocLlmEstimate,
} from '../services/api';
import type { TextExtractionUiStatus } from './useTextExtraction';

/**
 * V1.2.2：目录查询与三层识别入口。
 * GET /toc 本身是惰性识别（首访自动跑免费层）；文本提取从非 ok 变为 ok 且
 * 目录仍无结果时自动重查一次（启发式层此前被跳过，规格 F4）。
 */
export function useToc(pdfId: string | undefined, textStatus: TextExtractionUiStatus) {
  const [toc, setToc] = useState<TocInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const load = useCallback(
    async (fetcher: (id: string) => Promise<TocInfo>) => {
      if (!pdfId) return;
      const generation = ++generationRef.current;
      setLoading(true);
      setError(null);
      try {
        const data = await fetcher(pdfId);
        if (generationRef.current !== generation) return;
        setToc(data);
      } catch (err) {
        if (generationRef.current !== generation) return;
        setError(err instanceof Error ? err.message : '目录加载失败');
      } finally {
        if (generationRef.current === generation) setLoading(false);
      }
    },
    [pdfId],
  );

  useEffect(() => {
    setToc(null);
    if (pdfId) void load(getToc);
  }, [pdfId, load]);

  // 提取完成后目录若仍无结果，自动重跑免费层（启发式此前因文本未就绪被跳过）
  const retriedAfterExtractionRef = useRef(false);
  useEffect(() => {
    if (textStatus !== 'ok') return;
    if (retriedAfterExtractionRef.current) return;
    if (toc && toc.status === 'none' && toc.text_status !== 'ok') {
      retriedAfterExtractionRef.current = true;
      void load(recognizeToc);
    }
  }, [textStatus, toc, load]);

  useEffect(() => {
    retriedAfterExtractionRef.current = false;
  }, [pdfId]);

  const recognize = useCallback(() => load(recognizeToc), [load]);
  const recognizeLlm = useCallback(() => load(recognizeTocWithLlm), [load]);
  const fetchEstimate = useCallback((): Promise<TocLlmEstimate> => {
    if (!pdfId) return Promise.reject(new Error('no pdf'));
    return getTocLlmEstimate(pdfId);
  }, [pdfId]);

  return { toc, loading, error, recognize, fetchEstimate, recognizeLlm };
}

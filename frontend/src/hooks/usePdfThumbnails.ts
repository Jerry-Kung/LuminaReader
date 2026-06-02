/**
 * V1.0.4 F1 缩略图按需渲染 hook。
 *
 * 行为：
 *  - `getThumbnail(pageNumber)` 返回 dataURL；首次调用排入渲染队列，渲染完成后返回
 *  - LRU 缓存（容量 50）；超过容量自动驱逐最久未访问的条目
 *  - 串行渲染队列：同一时刻最多 1 个 PDF.js renderTask 在跑，避免大书并发 OOM / 抢占主 PDF 渲染
 *  - 切书（pdfDoc 变化）→ 清空缓存与队列
 *  - 目标宽度 ~120px：基于 PDF 第 1 页 viewport 反推 scale，所有页用同一 scale，视觉整齐
 *
 * 用法：
 *   const { getThumbnail } = usePdfThumbnails(pdfDoc);
 *   // 在 IntersectionObserver 观察到的可见项中：
 *   useEffect(() => {
 *     let cancelled = false;
 *     getThumbnail(pageNumber).then((url) => { if (!cancelled) setUrl(url); });
 *     return () => { cancelled = true; };
 *   }, [pageNumber]);
 */
import { useCallback, useEffect, useRef } from 'react';
import type * as pdfjsLib from 'pdfjs-dist';

const LRU_CAPACITY = 50;
const TARGET_WIDTH_PX = 120;

interface RenderJob {
  pageNumber: number;
  resolve: (url: string) => void;
  reject: (err: unknown) => void;
}

export function usePdfThumbnails(pdfDoc: pdfjsLib.PDFDocumentProxy | null): {
  getThumbnail: (pageNumber: number) => Promise<string>;
} {
  // Map 在 JS 中迭代顺序即插入顺序，访问时 delete + set 可实现 LRU。
  const cacheRef = useRef<Map<number, string>>(new Map());
  const queueRef = useRef<RenderJob[]>([]);
  const inFlightRef = useRef<Set<number>>(new Set());
  const runningRef = useRef<boolean>(false);
  // 同 doc 下所有页共用的 scale，第一次访问时计算并缓存。
  const scaleRef = useRef<number | null>(null);
  const docRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

  // 切书：清空缓存与队列；正在排队的请求 reject。
  useEffect(() => {
    docRef.current = pdfDoc;
    scaleRef.current = null;
    cacheRef.current.clear();
    inFlightRef.current.clear();
    const pendingJobs = queueRef.current;
    queueRef.current = [];
    pendingJobs.forEach((job) => job.reject(new Error('pdf changed')));
  }, [pdfDoc]);

  const computeScale = useCallback(
    async (doc: pdfjsLib.PDFDocumentProxy): Promise<number> => {
      if (scaleRef.current !== null) return scaleRef.current;
      const firstPage = await doc.getPage(1);
      const viewport = firstPage.getViewport({ scale: 1 });
      const scale = TARGET_WIDTH_PX / viewport.width;
      scaleRef.current = scale;
      return scale;
    },
    [],
  );

  const renderOne = useCallback(
    async (doc: pdfjsLib.PDFDocumentProxy, pageNumber: number): Promise<string> => {
      const scale = await computeScale(doc);
      const page = await doc.getPage(pageNumber);
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(viewport.width));
      canvas.height = Math.max(1, Math.round(viewport.height));
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('canvas 2d context unavailable');
      await page.render({ canvasContext: ctx, viewport }).promise;
      return canvas.toDataURL('image/png');
    },
    [computeScale],
  );

  const pump = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const job = queueRef.current.shift()!;
        const doc = docRef.current;
        if (!doc) {
          job.reject(new Error('pdf not loaded'));
          inFlightRef.current.delete(job.pageNumber);
          continue;
        }
        // 缓存命中（可能在排队期间被其他请求触发完成）
        const hit = cacheRef.current.get(job.pageNumber);
        if (hit !== undefined) {
          cacheRef.current.delete(job.pageNumber);
          cacheRef.current.set(job.pageNumber, hit);
          inFlightRef.current.delete(job.pageNumber);
          job.resolve(hit);
          continue;
        }
        try {
          const url = await renderOne(doc, job.pageNumber);
          // 渲染完成期间可能已切书：仅当 docRef 未变才入缓存
          if (docRef.current === doc) {
            cacheRef.current.set(job.pageNumber, url);
            while (cacheRef.current.size > LRU_CAPACITY) {
              const oldestKey = cacheRef.current.keys().next().value;
              if (oldestKey === undefined) break;
              cacheRef.current.delete(oldestKey);
            }
          }
          job.resolve(url);
        } catch (err) {
          job.reject(err);
        } finally {
          inFlightRef.current.delete(job.pageNumber);
        }
      }
    } finally {
      runningRef.current = false;
    }
  }, [renderOne]);

  const getThumbnail = useCallback(
    (pageNumber: number): Promise<string> => {
      const doc = docRef.current;
      if (!doc) return Promise.reject(new Error('pdf not loaded'));
      if (!Number.isInteger(pageNumber) || pageNumber < 1 || pageNumber > doc.numPages) {
        return Promise.reject(new Error(`page ${pageNumber} out of range`));
      }
      // 缓存命中：调整 LRU 顺序后直接返回
      const hit = cacheRef.current.get(pageNumber);
      if (hit !== undefined) {
        cacheRef.current.delete(pageNumber);
        cacheRef.current.set(pageNumber, hit);
        return Promise.resolve(hit);
      }
      // 进行中的相同请求：合并为新的 Promise（找队列里既有 job 的 promise 不直接可达，
      // 简化策略——重复入队，pump 时缓存命中分支会兜住）
      return new Promise<string>((resolve, reject) => {
        queueRef.current.push({ pageNumber, resolve, reject });
        inFlightRef.current.add(pageNumber);
        void pump();
      });
    },
    [pump],
  );

  return { getThumbnail };
}

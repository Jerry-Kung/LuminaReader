import { useCallback, useEffect, useState } from 'react';
import { normalizeSelectionText } from '../utils/normalize';

/**
 * V1.1.4 FE-4 / FE-5：跨页文本选区抓取 hook（取代 PDFViewer 内部的 PoC-2 effect）。
 *
 * 行为：
 *  - enabled=true 时，监听 containerRef 内 mouseup；推迟一拍后读 window.getSelection()
 *  - 仅当 Selection 完全落在 container 内才处理（避免抓到 UI 工具栏文本）
 *  - 按 [data-page] 拆 segments；每段 raw 文本由 normalizeSelectionText 归一化
 *  - selection collapse / 无交集时 → 不动 state（保留已有 selection；UI 端可调 clear() 显式清）
 *  - enabled=false 时移除 listener，并同步清空 state + 浏览器原生 Selection（避免残留）
 *
 * 不在本 hook 职责内：
 *  - 扫描版（textContent 全空）检测 → 留给 PDFPage 在 textLayer 渲染完成后上报
 *  - 浏览器原生 Selection 的视觉高亮 → 由 PDF.js textLayer + 默认浏览器选区行为提供
 */

export interface TextSelectionSegment {
  page: number;
  text: string;
}

export interface TextSelectionResult {
  segments: TextSelectionSegment[];
  rawText: string;
  normalizedText: string;
  pageStart: number;
  pageEnd: number;
  wordCount: number;
}

interface UseTextSelectionOptions {
  containerRef: React.RefObject<HTMLElement | null>;
  enabled: boolean;
}

interface UseTextSelectionResult {
  selection: TextSelectionResult | null;
  clear: () => void;
}

export function useTextSelection({
  containerRef,
  enabled,
}: UseTextSelectionOptions): UseTextSelectionResult {
  const [selection, setSelection] = useState<TextSelectionResult | null>(null);

  const clear = useCallback(() => {
    setSelection(null);
    try {
      window.getSelection()?.removeAllRanges();
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      // 关 cursorMode 'text' 时主动清掉残留状态与浏览器原生 Selection
      setSelection(null);
      try {
        window.getSelection()?.removeAllRanges();
      } catch {
        /* ignore */
      }
      return;
    }
    const el = containerRef.current;
    if (!el) return;

    const onMouseUp = () => {
      // 推迟一拍，等浏览器把 Selection 落定
      window.setTimeout(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || sel.rangeCount === 0) return;
        const range = sel.getRangeAt(0);
        // 仅当 Selection 完全落在容器内才处理
        if (!el.contains(range.commonAncestorContainer)) return;

        const pages = Array.from(el.querySelectorAll<HTMLElement>('[data-page]'));
        const segments: TextSelectionSegment[] = [];
        for (const pageEl of pages) {
          const pageNum = Number(pageEl.dataset.page);
          if (!Number.isFinite(pageNum)) continue;
          // 与 range 求与本页的交集
          const sub = document.createRange();
          sub.selectNodeContents(pageEl);
          const cmpStart = range.compareBoundaryPoints(Range.START_TO_START, sub);
          const cmpEnd = range.compareBoundaryPoints(Range.END_TO_END, sub);
          if (cmpStart > 0) sub.setStart(range.startContainer, range.startOffset);
          if (cmpEnd < 0) sub.setEnd(range.endContainer, range.endOffset);
          const raw = sub.toString();
          if (raw.trim().length > 0) {
            segments.push({ page: pageNum, text: raw });
          }
          sub.detach?.();
        }
        if (segments.length === 0) return;

        const combined = segments.map((s) => s.text).join('\n\n');
        const normalizedText = normalizeSelectionText(combined);
        if (!normalizedText) return;
        const wordCount = normalizedText.trim().split(/\s+/).filter(Boolean).length;

        setSelection({
          segments,
          rawText: combined,
          normalizedText,
          pageStart: segments[0].page,
          pageEnd: segments[segments.length - 1].page,
          wordCount,
        });
      }, 0);
    };

    el.addEventListener('mouseup', onMouseUp);
    return () => {
      el.removeEventListener('mouseup', onMouseUp);
    };
  }, [containerRef, enabled]);

  return { selection, clear };
}

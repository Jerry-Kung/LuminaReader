import { useCallback, useEffect, useState } from 'react';
import { normalizeSelectionText } from '../utils/normalize';

/**
 * V1.1.4 FE-4 / FE-5：跨页文本选区抓取 hook（取代 PDFViewer 内部的 PoC-2 effect）。
 *
 * 行为：
 *  - enabled=true 时，监听 containerRef 内 mouseup；推迟一拍后读 window.getSelection()
 *  - 仅当 Selection 完全落在 container 内才处理（避免抓到 UI 工具栏文本）
 *  - 按 [data-page] 拆 segments；每段 raw 文本由 normalizeSelectionText 归一化
 *  - V1.2.0 ISSUE-009：同步计算各页选区矩形（页内相对坐标 0~1 分数），供 PDFViewer
 *    渲染持久化高亮层。分数坐标随页面尺寸等比缩放，滚动 / 边栏宽度变化 / 缩放均无需重算。
 *  - selection collapse / 无交集时 → 不动 state（保留已有 selection；UI 端可调 clear() 显式清）
 *  - enabled=false 时移除 listener，并同步清空 state + 浏览器原生 Selection（避免残留）
 *
 * 不在本 hook 职责内：
 *  - 扫描版（textContent 全空）检测 → 留给 PDFPage 在 textLayer 渲染完成后上报
 *  - 高亮矩形的渲染 → 由 PDFViewer / PDFPage 按 pageRects 渲染（V1.2.0 起不再依赖
 *    浏览器原生 ::selection 提供视觉反馈，焦点移入 AI 输入框后高亮不消失）
 */

export interface TextSelectionSegment {
  page: number;
  text: string;
}

/** 单个高亮矩形，相对所在页的 0~1 分数坐标 */
export interface TextSelectionRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface TextSelectionPageRects {
  page: number;
  rects: TextSelectionRect[];
}

export interface TextSelectionResult {
  segments: TextSelectionSegment[];
  rawText: string;
  normalizedText: string;
  pageStart: number;
  pageEnd: number;
  wordCount: number;
  /** V1.2.0 ISSUE-009：各页选区高亮矩形（页内相对坐标） */
  pageRects: TextSelectionPageRects[];
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
        const pageRects: TextSelectionPageRects[] = [];
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
            // ISSUE-009：mouseup 时一次性把选区矩形换算成页内相对坐标（0~1 分数）。
            // 之后不再依赖 Range 节点存活，textLayer 重渲染 / 缩放 / 宽度变化都不需重算。
            const pageBox = pageEl.getBoundingClientRect();
            if (pageBox.width > 0 && pageBox.height > 0) {
              const rects: TextSelectionRect[] = [];
              for (const r of Array.from(sub.getClientRects())) {
                if (r.width < 1 || r.height < 1) continue; // 过滤零宽/零高碎片
                const left = (r.left - pageBox.left) / pageBox.width;
                const top = (r.top - pageBox.top) / pageBox.height;
                const width = r.width / pageBox.width;
                const height = r.height / pageBox.height;
                rects.push({
                  left: Math.max(0, Math.min(1, left)),
                  top: Math.max(0, Math.min(1, top)),
                  width: Math.max(0, Math.min(1 - Math.max(0, left), width)),
                  height: Math.max(0, Math.min(1 - Math.max(0, top), height)),
                });
              }
              if (rects.length > 0) pageRects.push({ page: pageNum, rects });
            }
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
          pageRects,
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

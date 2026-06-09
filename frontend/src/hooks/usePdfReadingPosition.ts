/**
 * V1.0.4 F9 / V1.1.3 F5 阅读位置持久化 hook。
 *
 * 行为：
 *  - `enabled=false` 时（restore 未完成 / 无 pdfId）完全静默：不排队、不写、不 flush
 *  - `enabled=true` 后监听 `(currentPage, currentOffset)` 变化，1s debounce 调
 *    PATCH /api/v1/pdfs/{id}/reading-position（body 含 last_read_page + last_read_offset）
 *  - 切书（pdfId 变化）/ 卸载 / `beforeunload` 三处 flush 一次最新值
 *  - 同一值多次写不重复请求（按 (page, offset) 联合去重，offset 容差 1e-6）
 *  - 写失败仅 console.warn，不阻塞 UI（debounce 写属"幂等记忆"，下次翻页 / 滚动会自然重试）
 *
 * 关键约束：`enabled` 必须由调用方在"阅读位置恢复完成"之后才置 true。
 * 否则 ReaderPage 入场时 (currentPage=1, currentOffset=0) 会被排队写入，
 * 覆盖 DB 中真实的 last_read_page / last_read_offset。
 *
 * 不在本 hook 范围：
 *  - 上界 clamp（由调用方根据 PDF.js numPages 完成；hook 只接受 >= 1 的整数）
 *  - 进入阅读器时的恢复跳转（由 ReaderPage 在拿到 last_read_page/offset + numPages 后调一次 goToPosition）
 */
import { useCallback, useEffect, useRef } from 'react';
import { updateReadingPosition } from '../services/api';

const DEBOUNCE_MS = 1000;
const OFFSET_EPSILON = 1e-6;

interface SentRecord {
  pdfId: string;
  page: number;
  offset: number;
}

function sameRecord(a: SentRecord, b: SentRecord): boolean {
  return (
    a.pdfId === b.pdfId &&
    a.page === b.page &&
    Math.abs(a.offset - b.offset) < OFFSET_EPSILON
  );
}

export function usePdfReadingPosition(
  pdfId: string | undefined,
  currentPage: number,
  currentOffset: number,
  enabled: boolean,
): { flushNow: () => void } {
  const timerRef = useRef<number | null>(null);
  const lastSentRef = useRef<SentRecord | null>(null);
  const pendingRef = useRef<SentRecord | null>(null);

  const send = useCallback((record: SentRecord) => {
    if (!Number.isInteger(record.page) || record.page < 1) return;
    if (!Number.isFinite(record.offset) || record.offset < 0 || record.offset > 1) return;
    const last = lastSentRef.current;
    if (last && sameRecord(last, record)) return;
    lastSentRef.current = record;
    updateReadingPosition(record.pdfId, record.page, record.offset).catch((err) => {
      // 失败时回退 lastSent，让下一次值变化能重试
      lastSentRef.current = last;
      console.warn('[reading-position] update failed:', err);
    });
  }, []);

  const flushNow = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    const pending = pendingRef.current;
    if (pending) {
      pendingRef.current = null;
      send(pending);
    }
  }, [send]);

  // pdfId 切换 → 立即 flush 旧书的 pending（用旧 pdfId）后清状态
  const prevPdfIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (prevPdfIdRef.current && prevPdfIdRef.current !== pdfId) {
      flushNow();
      lastSentRef.current = null;
    }
    prevPdfIdRef.current = pdfId;
  }, [pdfId, flushNow]);

  // 翻页 / 偏移变化 → 排队一次 debounce 写
  useEffect(() => {
    if (!enabled) return;
    if (!pdfId) return;
    if (!Number.isInteger(currentPage) || currentPage < 1) return;
    const offset = Math.max(0, Math.min(1, currentOffset));
    pendingRef.current = { pdfId, page: currentPage, offset };
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      const pending = pendingRef.current;
      if (pending) {
        pendingRef.current = null;
        send(pending);
      }
    }, DEBOUNCE_MS);
  }, [enabled, pdfId, currentPage, currentOffset, send]);

  // beforeunload → 同步 flush（fetch 是异步的，浏览器会尽力发出）
  useEffect(() => {
    const handler = () => flushNow();
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [flushNow]);

  // 卸载 → flush 一次
  useEffect(() => {
    return () => {
      flushNow();
    };
  }, [flushNow]);

  return { flushNow };
}

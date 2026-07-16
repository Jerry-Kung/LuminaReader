import { useCallback, useEffect, useRef, useState } from 'react';
import {
  getTextExtraction,
  triggerTextExtraction,
  type TextExtractionInfo,
  type TextExtractionStatus,
} from '../services/api';

const POLL_INTERVAL_MS = 2000;

export type TextExtractionUiStatus = TextExtractionStatus | 'loading' | 'error';

/**
 * V1.2.1：全书文本提取状态查询 + 手动触发 + pending 轮询。
 * status 为 'loading'（首查中）/ 'error'（查询失败，静默不打扰）/ 后端五态之一。
 */
export function useTextExtraction(pdfId: string | undefined) {
  const [status, setStatus] = useState<TextExtractionUiStatus>('loading');
  const [info, setInfo] = useState<TextExtractionInfo | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generationRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const refresh = useCallback(
    async (generation: number) => {
      if (!pdfId) return;
      try {
        const data = await getTextExtraction(pdfId);
        if (generationRef.current !== generation) return;
        setInfo(data);
        setStatus(data.status);
        if (data.status === 'pending') {
          pollTimerRef.current = setTimeout(() => refresh(generation), POLL_INTERVAL_MS);
        }
      } catch {
        if (generationRef.current !== generation) return;
        setStatus('error');
      }
    },
    [pdfId],
  );

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    stopPolling();
    setStatus('loading');
    setInfo(null);
    if (pdfId) {
      refresh(generation);
    }
    return () => {
      generationRef.current += 1;
      stopPolling();
    };
  }, [pdfId, refresh, stopPolling]);

  const trigger = useCallback(async () => {
    if (!pdfId) return;
    const generation = generationRef.current;
    try {
      await triggerTextExtraction(pdfId);
      if (generationRef.current !== generation) return;
      setStatus('pending');
      stopPolling();
      pollTimerRef.current = setTimeout(() => refresh(generation), POLL_INTERVAL_MS);
    } catch {
      if (generationRef.current !== generation) return;
      setStatus('error');
    }
  }, [pdfId, refresh, stopPolling]);

  return { status, info, trigger };
}

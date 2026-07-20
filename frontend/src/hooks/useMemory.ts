import { useCallback, useEffect, useRef, useState } from 'react';
import {
  buildMemory,
  cancelMemory,
  getMemory,
  getMemoryEstimate,
  rebuildMemory,
  type MemoryEstimate,
  type MemoryInfo,
} from '../services/api';

const POLL_INTERVAL_MS = 2000;

/**
 * V1.2.3：记忆状态查询 + running 态 2s 轮询 + build/rebuild/cancel 动作。
 * 动作函数把后端返回的最新状态直接写入本地 state，轮询由 status==='running' 驱动。
 */
export function useMemory(pdfId: string | undefined) {
  const [memory, setMemory] = useState<MemoryInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  const load = useCallback(async () => {
    if (!pdfId) return;
    const generation = ++generationRef.current;
    try {
      const data = await getMemory(pdfId);
      if (generationRef.current !== generation) return;
      setMemory(data);
      setError(null);
    } catch (err) {
      if (generationRef.current !== generation) return;
      setError(err instanceof Error ? err.message : '记忆状态加载失败');
    }
  }, [pdfId]);

  useEffect(() => {
    generationRef.current += 1;
    setMemory(null);
    setError(null);
    if (!pdfId) return;
    setLoading(true);
    void load().finally(() => setLoading(false));
  }, [pdfId, load]);

  // running 态轮询至终态
  useEffect(() => {
    if (!pdfId || memory?.status !== 'running') return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [pdfId, memory?.status, load]);

  const runAction = useCallback(
    async (action: (id: string) => Promise<MemoryInfo>) => {
      if (!pdfId) return;
      const data = await action(pdfId);
      setMemory(data);
    },
    [pdfId],
  );

  const build = useCallback(() => runAction(buildMemory), [runAction]);
  const rebuild = useCallback(() => runAction(rebuildMemory), [runAction]);
  const cancel = useCallback(() => runAction(cancelMemory), [runAction]);
  const fetchEstimate = useCallback((): Promise<MemoryEstimate> => {
    if (!pdfId) return Promise.reject(new Error('no pdf'));
    return getMemoryEstimate(pdfId);
  }, [pdfId]);

  return { memory, loading, error, fetchEstimate, build, rebuild, cancel };
}

/**
 * V1.2.2 目录 Tab：多级缩进树（子级可折叠）+ 当前章节高亮 + 分状态空态。
 * 空态三分支（规格 F4）：无目录（重新识别 / AI 识别入口）、扫描版不支持、文本未就绪。
 * LLM 入口先弹花费预估确认框（规格 §6.4 花费透明）。
 */
import { useMemo, useState } from 'react';
import type { TocChapter, TocInfo, TocLlmEstimate } from '@/services/api';
import CostEstimateDialog from './CostEstimateDialog';

interface TocTabProps {
  toc: TocInfo | null;
  loading: boolean;
  error: string | null;
  currentPage: number;
  onChapterClick: (page: number) => void;
  onRecognize: () => Promise<void>;
  onFetchEstimate: () => Promise<TocLlmEstimate>;
  onRecognizeLlm: () => Promise<void>;
}

export default function TocTab({
  toc,
  loading,
  error,
  currentPage,
  onChapterClick,
  onRecognize,
  onFetchEstimate,
  onRecognizeLlm,
}: TocTabProps) {
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());
  const [estimate, setEstimate] = useState<TocLlmEstimate | null>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [llmRunning, setLlmRunning] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);

  const childrenMap = useMemo(() => {
    const map = new Map<string | null, TocChapter[]>();
    (toc?.chapters ?? []).forEach((c) => {
      const list = map.get(c.parent_id) ?? [];
      list.push(c);
      map.set(c.parent_id, list);
    });
    return map;
  }, [toc]);

  // 当前章节 = preorder 中最后一个 start_page <= currentPage 的章节（页级粒度，known limitation 1）
  const activeChapterId = useMemo(() => {
    const chapters = toc?.chapters ?? [];
    let active: string | null = null;
    for (const c of chapters) {
      if (c.page <= currentPage) active = c.id;
    }
    return active;
  }, [toc, currentPage]);

  const toggleCollapse = (id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openEstimate = async () => {
    setEstimateLoading(true);
    setLlmError(null);
    try {
      setEstimate(await onFetchEstimate());
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : 'AI 识别暂不可用');
    } finally {
      setEstimateLoading(false);
    }
  };

  const confirmLlm = async () => {
    setEstimate(null);
    setLlmRunning(true);
    setLlmError(null);
    try {
      await onRecognizeLlm();
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : 'AI 识别失败，可重试');
    } finally {
      setLlmRunning(false);
    }
  };

  const renderNode = (chapter: TocChapter) => {
    const children = childrenMap.get(chapter.id) ?? [];
    const collapsed = collapsedIds.has(chapter.id);
    const isActive = chapter.id === activeChapterId;
    return (
      <div key={chapter.id}>
        <div
          onClick={() => onChapterClick(chapter.page)}
          style={{ paddingLeft: `${8 + chapter.depth * 14}px` }}
          className={`group flex items-center gap-1 pr-2 py-1.5 rounded cursor-pointer text-[12px] leading-snug transition-colors ${
            isActive
              ? 'bg-[#fef9f3] text-amber-700 border-l-2 border-amber-400'
              : 'text-stone-600 hover:bg-stone-200/40'
          }`}
          title={`${chapter.title}（第 ${chapter.page} 页）`}
        >
          {children.length > 0 ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleCollapse(chapter.id);
              }}
              className="w-4 h-4 flex-shrink-0 flex items-center justify-center text-stone-400 hover:text-stone-600"
            >
              <i className={`text-xs ${collapsed ? 'ri-arrow-right-s-line' : 'ri-arrow-down-s-line'}`} />
            </button>
          ) : (
            <span className="w-4 flex-shrink-0" />
          )}
          <span className="flex-1 truncate">{chapter.title}</span>
          <span className={`text-[10px] flex-shrink-0 ${isActive ? 'text-amber-500' : 'text-stone-400'}`}>
            {chapter.page}
          </span>
        </div>
        {!collapsed && children.map(renderNode)}
      </div>
    );
  };

  if (loading || llmRunning) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2 text-stone-400">
        <i className="ri-loader-4-line animate-spin text-lg" />
        <span className="text-[10px]">{llmRunning ? 'AI 识别中…' : '加载目录…'}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-3 py-4 text-[11px] text-stone-400 leading-relaxed">
        目录加载失败。
        <button onClick={() => void onRecognize()} className="text-amber-600 hover:underline ml-1 cursor-pointer">
          重试
        </button>
      </div>
    );
  }

  if (toc && toc.status === 'ready') {
    return (
      <div className="py-2 px-1">
        {(childrenMap.get(null) ?? []).map(renderNode)}
        <div className="mt-3 px-2">
          <button
            onClick={() => void onRecognize()}
            className="text-[10px] text-stone-400 hover:text-stone-600 cursor-pointer"
            title="按 outline → 启发式重新识别；识别失败时保留当前目录"
          >
            <i className="ri-refresh-line mr-0.5" />
            重新识别
          </button>
        </div>
      </div>
    );
  }

  // 无目录空态：按 text_status 分支
  const scanned = toc?.text_status === 'unsupported';
  const textPending = toc != null && !scanned && toc.text_status !== 'ok';
  return (
    <div className="px-3 py-4 text-[11px] text-stone-500 leading-relaxed space-y-3">
      {scanned ? (
        <p>扫描版 / 无文本层 PDF，不支持目录识别。</p>
      ) : textPending ? (
        <p>等待全书文本提取完成后可识别目录（见顶部状态条）。</p>
      ) : (
        <>
          <p>{toc?.status === 'failed' ? `AI 识别失败：${toc.error ?? '未知错误'}` : '未识别到本书目录。'}</p>
          <div className="flex flex-col gap-2">
            <button
              onClick={() => void onRecognize()}
              className="px-2.5 py-1.5 text-[11px] rounded-md bg-stone-100 text-stone-600 hover:bg-stone-200 transition-colors cursor-pointer text-left"
            >
              <i className="ri-refresh-line mr-1" />
              重新识别（免费）
            </button>
            {toc?.llm_available && (
              <button
                onClick={() => void openEstimate()}
                disabled={estimateLoading}
                className="px-2.5 py-1.5 text-[11px] rounded-md bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors cursor-pointer text-left disabled:opacity-50"
              >
                <i className="ri-sparkling-line mr-1" />
                {estimateLoading ? '获取花费预估…' : '用 AI 识别目录'}
              </button>
            )}
          </div>
          {llmError && <p className="text-red-400">{llmError}</p>}
        </>
      )}

      {/* 花费预估确认框（规格 §6.4：触发前展示花费预估） */}
      {estimate && (
        <CostEstimateDialog
          title="AI 识别目录 — 花费预估"
          model={estimate.model}
          inputTokens={estimate.estimated_input_tokens}
          cost={estimate.estimated_cost}
          confirmLabel="确认识别"
          onConfirm={() => void confirmLlm()}
          onCancel={() => setEstimate(null)}
        />
      )}
    </div>
  );
}

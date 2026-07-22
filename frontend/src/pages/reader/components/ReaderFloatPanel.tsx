/**
 * V1.2.5 通用非模态浮动面板（ISSUE-013）：悬浮阅读区左侧、单实例、按视图渲染。
 * 定位/关闭/尺寸等容器行为只实现一次；视图注册结构便于后续扩展（讨论项等）。
 * 本版视图：memory-unit（章节要点）/ book-summary（全书总结）；Task 5 扩展 note 视图。
 */
import { useEffect } from 'react';
import type { MemoryUnit } from '@/services/api';
import MarkdownRenderer from './MarkdownRenderer';

export type FloatPanelView =
  | { kind: 'memory-unit'; unit: MemoryUnit }
  | { kind: 'book-summary'; summary: string };

interface ReaderFloatPanelProps {
  view: FloatPanelView | null;
  sidebarCollapsed: boolean;
  onClose: () => void;
  onJumpToPage: (page: number) => void;
}

export default function ReaderFloatPanel({
  view,
  sidebarCollapsed,
  onClose,
  onJumpToPage,
}: ReaderFloatPanelProps) {
  // Esc 随时关闭（非模态，不抢焦点）
  useEffect(() => {
    if (!view) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [view, onClose]);

  if (!view) return null;

  let title = '';
  let icon = '';
  let jumpPage: number | null = null;
  let body: React.ReactNode = null;

  if (view.kind === 'memory-unit') {
    title = view.unit.title;
    icon = 'ri-sparkling-line';
    jumpPage = view.unit.start_page;
    body = view.unit.summary ? (
      <MarkdownRenderer content={view.unit.summary} className="text-[13px]" />
    ) : (
      <p className="text-xs text-stone-400">
        {view.unit.status === 'failed' ? `加工失败：${view.unit.error ?? '未知错误'}` : '尚未加工'}
      </p>
    );
  } else {
    title = '全书总结';
    icon = 'ri-book-open-line';
    body = <MarkdownRenderer content={view.summary} className="text-[13px]" />;
  }

  return (
    <div
      className={`absolute top-2 z-30 w-[420px] max-w-[60vw] max-h-[calc(100%-1rem)] flex flex-col rounded-lg border border-stone-200 bg-white shadow-xl ${
        sidebarCollapsed ? 'left-10' : 'left-[188px]'
      }`}
    >
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-2 border-b border-stone-100">
        <i className={`${icon} text-amber-600 text-sm flex-shrink-0`} />
        <span className="flex-1 truncate text-[13px] font-medium text-stone-700" title={title}>
          {title}
        </span>
        {jumpPage !== null && (
          <button
            onClick={() => onJumpToPage(jumpPage!)}
            className="flex-shrink-0 px-1.5 py-0.5 text-[11px] text-stone-400 hover:text-amber-600 rounded cursor-pointer"
            title={`跳转到第 ${jumpPage} 页`}
          >
            p.{jumpPage}
          </button>
        )}
        <button
          onClick={onClose}
          className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 cursor-pointer"
          title="关闭（Esc）"
        >
          <i className="ri-close-line text-sm" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-3">{body}</div>
    </div>
  );
}

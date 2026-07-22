/**
 * V1.2.5 通用非模态浮动面板（ISSUE-013）：悬浮阅读区左侧、单实例、按视图渲染。
 * 定位/关闭/尺寸等容器行为只实现一次；视图注册结构便于后续扩展（讨论项等）。
 * 本版视图：memory-unit（章节要点）/ book-summary（全书总结）/ note（笔记详情）/ note-new（新建笔记）。
 */
import { useEffect, useState } from 'react';
import type { MemoryUnit, NoteItem, NoteSource } from '@/services/api';
import MarkdownRenderer from './MarkdownRenderer';

export interface NoteDraft {
  page: number;
  offset_ratio?: number;
  anchor_text?: string;
  anchor_rects_json?: string;
  source: NoteSource;
}

export type FloatPanelView =
  | { kind: 'memory-unit'; unit: MemoryUnit }
  | { kind: 'book-summary'; summary: string }
  | { kind: 'note'; noteId: string }
  | { kind: 'note-new'; draft: NoteDraft };

interface ReaderFloatPanelProps {
  view: FloatPanelView | null;
  sidebarCollapsed: boolean;
  notes: NoteItem[];
  onClose: () => void;
  onJumpToPage: (page: number) => void;
  onJumpToNote: (note: NoteItem) => void;
  onSubmitNewNote: (draft: NoteDraft, content: string) => Promise<void>;
  onUpdateNote: (id: string, content: string) => Promise<void>;
  onDeleteNote: (id: string) => Promise<void>;
}

const SOURCE_META: Record<NoteSource, { icon: string; label: string }> = {
  manual: { icon: 'ri-sticky-note-line', label: '手动' },
  selection: { icon: 'ri-text', label: '选区' },
  ai: { icon: 'ri-robot-2-line', label: 'AI' },
};

function NoteView({
  note,
  onJumpToNote,
  onUpdate,
  onDelete,
}: {
  note: NoteItem;
  onJumpToNote: (note: NoteItem) => void;
  onUpdate: (id: string, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.content);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 切换到另一条笔记时重置编辑态
  useEffect(() => {
    setEditing(false);
    setDraft(note.content);
    setError(null);
  }, [note.id, note.content]);

  const save = async () => {
    const content = draft.trim();
    if (!content) {
      setError('笔记内容不能为空');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onUpdate(note.id, content);
      setEditing(false);
    } catch {
      setError('保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {note.anchor_text && (
        <blockquote
          onClick={() => onJumpToNote(note)}
          className="px-3 py-2 rounded bg-stone-50 border-l-2 border-amber-300 text-[12px] text-stone-500 leading-relaxed cursor-pointer hover:bg-stone-100 transition-colors"
          title="点击跳转到原文位置"
        >
          {note.anchor_text}
        </blockquote>
      )}
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full h-48 text-[13px] text-stone-700 bg-stone-50 border border-stone-200 rounded-lg px-3 py-2 resize-y focus:outline-none focus:border-amber-400 leading-relaxed"
            placeholder="Markdown 正文…"
          />
          <div className="flex items-center gap-2">
            <button
              onClick={() => void save()}
              disabled={saving}
              className="px-3 py-1 text-[12px] rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 cursor-pointer"
            >
              {saving ? '保存中…' : '保存'}
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setDraft(note.content);
                setError(null);
              }}
              className="px-3 py-1 text-[12px] rounded-md text-stone-500 hover:bg-stone-100 cursor-pointer"
            >
              取消
            </button>
            {error && <span className="text-[11px] text-red-400">{error}</span>}
          </div>
        </div>
      ) : (
        <>
          <MarkdownRenderer content={note.content} className="text-[13px]" />
          <div className="flex items-center gap-2 pt-2 border-t border-stone-100">
            <button
              onClick={() => setEditing(true)}
              className="px-2 py-1 text-[11px] text-stone-500 hover:text-stone-700 hover:bg-stone-100 rounded cursor-pointer"
            >
              <i className="ri-pencil-line mr-0.5" />
              编辑
            </button>
            <button
              onClick={() => void onDelete(note.id)}
              className="px-2 py-1 text-[11px] text-stone-400 hover:text-red-500 hover:bg-red-50 rounded cursor-pointer"
            >
              <i className="ri-delete-bin-line mr-0.5" />
              删除
            </button>
            <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-stone-300">
              <i className={SOURCE_META[note.source].icon} />
              {SOURCE_META[note.source].label}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function NoteNewView({
  draft,
  onSubmit,
}: {
  draft: NoteDraft;
  onSubmit: (draft: NoteDraft, content: string) => Promise<void>;
}) {
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const trimmed = content.trim();
    if (!trimmed) {
      setError('笔记内容不能为空');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit(draft, trimmed);
    } catch {
      setError('保存失败，请重试');
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      {draft.anchor_text && (
        <blockquote className="px-3 py-2 rounded bg-stone-50 border-l-2 border-amber-300 text-[12px] text-stone-500 leading-relaxed">
          {draft.anchor_text}
        </blockquote>
      )}
      <textarea
        autoFocus
        value={content}
        onChange={(e) => setContent(e.target.value)}
        className="w-full h-48 text-[13px] text-stone-700 bg-stone-50 border border-stone-200 rounded-lg px-3 py-2 resize-y focus:outline-none focus:border-amber-400 leading-relaxed"
        placeholder="写点什么…（支持 Markdown）"
      />
      <div className="flex items-center gap-2">
        <button
          onClick={() => void save()}
          disabled={saving}
          className="px-3 py-1 text-[12px] rounded-md bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50 cursor-pointer"
        >
          {saving ? '保存中…' : '保存'}
        </button>
        {error && <span className="text-[11px] text-red-400">{error}</span>}
      </div>
    </div>
  );
}

export default function ReaderFloatPanel({
  view,
  sidebarCollapsed,
  notes,
  onClose,
  onJumpToPage,
  onJumpToNote,
  onSubmitNewNote,
  onUpdateNote,
  onDeleteNote,
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
  let jumpHandler: () => void = () => {};
  let body: React.ReactNode = null;

  if (view.kind === 'memory-unit') {
    title = view.unit.title;
    icon = 'ri-sparkling-line';
    jumpPage = view.unit.start_page;
    jumpHandler = () => onJumpToPage(view.unit.start_page);
    body = view.unit.summary ? (
      <MarkdownRenderer content={view.unit.summary} className="text-[13px]" />
    ) : (
      <p className="text-xs text-stone-400">
        {view.unit.status === 'failed' ? `加工失败：${view.unit.error ?? '未知错误'}` : '尚未加工'}
      </p>
    );
  } else if (view.kind === 'book-summary') {
    title = '全书总结';
    icon = 'ri-book-open-line';
    body = <MarkdownRenderer content={view.summary} className="text-[13px]" />;
  } else if (view.kind === 'note') {
    const note = notes.find((n) => n.id === view.noteId);
    title = '笔记';
    icon = 'ri-sticky-note-line';
    jumpPage = note?.page ?? null;
    jumpHandler = note ? () => onJumpToNote(note) : () => {};
    body = note ? (
      <NoteView note={note} onJumpToNote={onJumpToNote} onUpdate={onUpdateNote} onDelete={onDeleteNote} />
    ) : (
      <p className="text-xs text-stone-400">该笔记已被删除。</p>
    );
  } else {
    title = '新建笔记';
    icon = 'ri-sticky-note-add-line';
    jumpPage = view.draft.page;
    jumpHandler = () => onJumpToPage(view.draft.page);
    body = <NoteNewView draft={view.draft} onSubmit={onSubmitNewNote} />;
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
            onClick={jumpHandler}
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

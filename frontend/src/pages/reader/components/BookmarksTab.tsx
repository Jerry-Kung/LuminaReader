/**
 * V1.2.2 书签 Tab：按页码排序列表 + 顶部添加按钮 + hover 重命名/删除 + 新建就地改名。
 * 删除为硬删除、无确认弹窗（规格 F3：轻量数据，与选区删除交互档位一致）。
 */
import { useEffect, useRef, useState } from 'react';
import type { BookmarkItem } from '@/services/api';

interface BookmarksTabProps {
  bookmarks: BookmarkItem[];
  loading: boolean;
  editingId: string | null;
  onEditingDone: () => void;
  onAdd: () => Promise<void>;
  onRename: (id: string, name: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  onJump: (page: number, offsetRatio: number) => void;
}

export default function BookmarksTab({
  bookmarks,
  loading,
  editingId,
  onEditingDone,
  onAdd,
  onRename,
  onRemove,
  onJump,
}: BookmarksTabProps) {
  const [adding, setAdding] = useState(false);

  const handleAdd = async () => {
    setAdding(true);
    try {
      await onAdd();
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="py-2 px-2 space-y-2">
      <button
        onClick={() => void handleAdd()}
        disabled={adding}
        className="w-full px-2.5 py-1.5 text-[11px] rounded-md bg-stone-100 text-stone-600 hover:bg-stone-200 transition-colors cursor-pointer disabled:opacity-50"
      >
        <i className="ri-bookmark-line mr-1" />
        在当前位置添加书签
      </button>

      {loading && (
        <div className="flex justify-center py-6 text-stone-400">
          <i className="ri-loader-4-line animate-spin" />
        </div>
      )}

      {!loading && bookmarks.length === 0 && (
        <p className="px-1 py-4 text-[11px] text-stone-400 leading-relaxed">
          还没有书签。点击上方按钮，或工具栏的书签按钮，记录当前阅读位置。
        </p>
      )}

      {!loading &&
        bookmarks.map((b) => (
          <BookmarkRow
            key={b.id}
            bookmark={b}
            editing={editingId === b.id}
            onEditingDone={onEditingDone}
            onRename={onRename}
            onRemove={onRemove}
            onJump={onJump}
          />
        ))}
    </div>
  );
}

interface BookmarkRowProps {
  bookmark: BookmarkItem;
  editing: boolean;
  onEditingDone: () => void;
  onRename: (id: string, name: string) => Promise<void>;
  onRemove: (id: string) => Promise<void>;
  onJump: (page: number, offsetRatio: number) => void;
}

function BookmarkRow({ bookmark, editing, onEditingDone, onRename, onRemove, onJump }: BookmarkRowProps) {
  const [localEditing, setLocalEditing] = useState(false);
  const [draft, setDraft] = useState(bookmark.name);
  const inputRef = useRef<HTMLInputElement>(null);
  const isEditing = editing || localEditing;

  useEffect(() => {
    if (isEditing) {
      setDraft(bookmark.name);
      // 渲染后聚焦全选，直接输入即覆盖默认名"第 N 页"
      requestAnimationFrame(() => inputRef.current?.select());
    }
  }, [isEditing, bookmark.name]);

  const commit = async () => {
    const name = draft.trim();
    setLocalEditing(false);
    onEditingDone();
    if (name && name !== bookmark.name) {
      try {
        await onRename(bookmark.id, name);
      } catch {
        /* 改名失败保留旧名，列表状态未变 */
      }
    }
  };

  if (isEditing) {
    return (
      <div className="px-2 py-1.5 rounded-md bg-white border border-amber-300">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit();
            if (e.key === 'Escape') {
              setDraft(bookmark.name);
              setLocalEditing(false);
              onEditingDone();
            }
          }}
          className="w-full text-[12px] text-stone-700 bg-transparent focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div
      onClick={() => onJump(bookmark.page, bookmark.offset_ratio)}
      className="group flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-white border border-stone-200/60 hover:border-stone-300/80 cursor-pointer transition-colors"
    >
      <i className="ri-bookmark-fill text-amber-400 text-xs flex-shrink-0" />
      <span className="flex-1 truncate text-[12px] text-stone-600" title={bookmark.name}>
        {bookmark.name}
      </span>
      <span className="text-[10px] text-stone-400 flex-shrink-0">p.{bookmark.page}</span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setLocalEditing(true);
        }}
        className="hidden group-hover:flex w-5 h-5 items-center justify-center rounded text-stone-400 hover:text-stone-600 cursor-pointer"
        title="重命名"
      >
        <i className="ri-pencil-line text-xs" />
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          void onRemove(bookmark.id);
        }}
        className="hidden group-hover:flex w-5 h-5 items-center justify-center rounded text-stone-400 hover:text-red-500 cursor-pointer"
        title="删除"
      >
        <i className="ri-delete-bin-line text-xs" />
      </button>
    </div>
  );
}

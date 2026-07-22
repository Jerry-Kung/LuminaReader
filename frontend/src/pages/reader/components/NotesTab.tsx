/**
 * V1.2.5 笔记 Tab：列表（首行摘要 + 页码 + 来源图标）+ 顶部新建按钮 + hover 删除。
 * 详情/编辑在浮动面板中完成（ISSUE-013 弹层结构），本 Tab 职责收敛为列表入口。
 */
import type { NoteItem, NoteSource } from '@/services/api';

interface NotesTabProps {
  notes: NoteItem[];
  loading: boolean;
  onCreate: () => void;
  onOpen: (note: NoteItem) => void;
  onRemove: (id: string) => Promise<void>;
  onJump: (note: NoteItem) => void;
}

const SOURCE_ICON: Record<NoteSource, { icon: string; label: string }> = {
  manual: { icon: 'ri-sticky-note-line', label: '手动笔记' },
  selection: { icon: 'ri-text', label: '选区笔记' },
  ai: { icon: 'ri-robot-2-line', label: 'AI 回答' },
};

function firstLine(content: string): string {
  const line = content.split('\n').find((l) => l.trim().length > 0) ?? '';
  // 去掉行首 Markdown 标记（# / - / > 等），仅为列表摘要显示
  return line.replace(/^[#>\-*\s]+/, '').slice(0, 60) || '（空）';
}

export default function NotesTab({ notes, loading, onCreate, onOpen, onRemove, onJump }: NotesTabProps) {
  return (
    <div className="py-2 px-2 space-y-2">
      <button
        onClick={onCreate}
        className="w-full px-2.5 py-1.5 text-[11px] rounded-md bg-stone-100 text-stone-600 hover:bg-stone-200 transition-colors cursor-pointer"
      >
        <i className="ri-sticky-note-add-line mr-1" />
        新建笔记（当前页）
      </button>

      {loading && (
        <div className="flex justify-center py-6 text-stone-400">
          <i className="ri-loader-4-line animate-spin" />
        </div>
      )}

      {!loading && notes.length === 0 && (
        <p className="px-1 py-4 text-[11px] text-stone-400 leading-relaxed">
          还没有笔记。点击上方按钮新建，或选中正文 / 在 AI 回答下方存为笔记。
        </p>
      )}

      {!loading &&
        notes.map((n) => (
          <div
            key={n.id}
            onClick={() => onOpen(n)}
            className="group flex items-center gap-1.5 px-2 py-1.5 rounded-md bg-white border border-stone-200/60 hover:border-stone-300/80 cursor-pointer transition-colors"
          >
            <i
              className={`${SOURCE_ICON[n.source].icon} text-amber-400 text-xs flex-shrink-0`}
              title={SOURCE_ICON[n.source].label}
            />
            <span className="flex-1 truncate text-[12px] text-stone-600" title={firstLine(n.content)}>
              {firstLine(n.content)}
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onJump(n);
              }}
              className="text-[10px] text-stone-400 hover:text-amber-600 flex-shrink-0 cursor-pointer"
              title={`跳转到第 ${n.page} 页`}
            >
              p.{n.page}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                void onRemove(n.id);
              }}
              className="hidden group-hover:flex w-5 h-5 items-center justify-center rounded text-stone-400 hover:text-red-500 cursor-pointer"
              title="删除"
            >
              <i className="ri-delete-bin-line text-xs" />
            </button>
          </div>
        ))}
    </div>
  );
}

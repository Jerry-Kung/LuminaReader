/**
 * V1.2.2 左侧栏三 Tab 容器：缩略图 / 目录 / 书签（规格 D2）。
 * 外壳（宽度 180px / 折叠 w-8 / 过渡动画）沿用原 ThumbnailPanel 行为不变；
 * V1.2.5 笔记可在此追加第四个 Tab。
 */
import { useState } from 'react';
import type * as pdfjsLib from 'pdfjs-dist';
import type { BookmarkItem, TocInfo, TocLlmEstimate } from '@/services/api';
import ThumbnailList from './ThumbnailPanel';
import TocTab from './TocTab';
import BookmarksTab from './BookmarksTab';

export type SidebarTab = 'thumbnails' | 'toc' | 'bookmarks';

interface SidebarPanelProps {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  numPages: number;
  currentPage: number;
  isLoading: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onPageClick: (page: number) => void;
  // 目录
  toc: TocInfo | null;
  tocLoading: boolean;
  tocError: string | null;
  onTocRecognize: () => Promise<void>;
  onTocFetchEstimate: () => Promise<TocLlmEstimate>;
  onTocRecognizeLlm: () => Promise<void>;
  // 书签
  bookmarks: BookmarkItem[];
  bookmarksLoading: boolean;
  editingBookmarkId: string | null;
  onBookmarkEditingDone: () => void;
  onBookmarkAdd: () => Promise<void>;
  onBookmarkRename: (id: string, name: string) => Promise<void>;
  onBookmarkRemove: (id: string) => Promise<void>;
  onBookmarkJump: (page: number, offsetRatio: number) => void;
}

const TABS: { key: SidebarTab; icon: string; label: string }[] = [
  { key: 'thumbnails', icon: 'ri-image-2-line', label: '页面' },
  { key: 'toc', icon: 'ri-list-unordered', label: '目录' },
  { key: 'bookmarks', icon: 'ri-bookmark-line', label: '书签' },
];

export default function SidebarPanel(props: SidebarPanelProps) {
  const { collapsed, onToggleCollapsed } = props;
  const [tab, setTab] = useState<SidebarTab>('thumbnails');

  return (
    <div
      className={`flex-shrink-0 flex flex-col border-r border-stone-200 bg-[#f7f4f0] transition-all duration-200 ease-out overflow-hidden ${
        collapsed ? 'w-8' : 'w-[180px]'
      }`}
    >
      {/* 顶部小栏：Tab 切换 + 折叠按钮（沿用原 ThumbnailPanel 外壳交互） */}
      <div className="flex-shrink-0 h-9 flex items-center border-b border-stone-200/60">
        {!collapsed ? (
          <div className="flex items-center justify-between w-full px-1.5">
            <div className="flex items-center gap-0.5">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`w-7 h-7 flex items-center justify-center rounded transition-colors cursor-pointer ${
                    tab === t.key
                      ? 'bg-stone-200/70 text-stone-700'
                      : 'text-stone-400 hover:bg-stone-200/50 hover:text-stone-600'
                  }`}
                  title={t.label}
                >
                  <i className={`${t.icon} text-sm`} />
                </button>
              ))}
            </div>
            <button
              onClick={onToggleCollapsed}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-stone-200/50 text-stone-400 hover:text-stone-600 transition-colors cursor-pointer"
              title="收起"
            >
              <i className="ri-arrow-left-s-line text-sm" />
            </button>
          </div>
        ) : (
          <div className="w-full flex justify-center pt-1.5">
            <button
              onClick={onToggleCollapsed}
              className="w-6 h-6 flex items-center justify-center rounded hover:bg-stone-200/50 text-stone-400 hover:text-stone-600 transition-colors cursor-pointer"
              title="展开"
            >
              <i className="ri-arrow-right-s-line text-sm" />
            </button>
          </div>
        )}
      </div>

      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {/* 缩略图保持挂载（display 切换），避免切 Tab 反复重建 LRU/observer */}
          <div className={tab === 'thumbnails' ? 'h-full flex flex-col' : 'hidden'}>
            <ThumbnailList
              pdfDoc={props.pdfDoc}
              numPages={props.numPages}
              currentPage={props.currentPage}
              onPageClick={props.onPageClick}
              isLoading={props.isLoading}
              active={tab === 'thumbnails' && !collapsed}
            />
          </div>
          {tab === 'toc' && (
            <div className="h-full overflow-y-auto scrollbar-thin">
              <TocTab
                toc={props.toc}
                loading={props.tocLoading}
                error={props.tocError}
                currentPage={props.currentPage}
                onChapterClick={props.onPageClick}
                onRecognize={props.onTocRecognize}
                onFetchEstimate={props.onTocFetchEstimate}
                onRecognizeLlm={props.onTocRecognizeLlm}
              />
            </div>
          )}
          {tab === 'bookmarks' && (
            <div className="h-full overflow-y-auto scrollbar-thin">
              <BookmarksTab
                bookmarks={props.bookmarks}
                loading={props.bookmarksLoading}
                editingId={props.editingBookmarkId}
                onEditingDone={props.onBookmarkEditingDone}
                onAdd={props.onBookmarkAdd}
                onRename={props.onBookmarkRename}
                onRemove={props.onBookmarkRemove}
                onJump={props.onBookmarkJump}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

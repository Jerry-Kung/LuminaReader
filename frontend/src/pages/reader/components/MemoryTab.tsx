/**
 * V1.2.3 要点 Tab：六状态呈现（none / 不可用 / running / partial / ready / failed）
 * + toc_changed 黄条（规格 F6）。所有付费动作先弹花费预估确认框（规格 §6.4）。
 */
import { useMemo, useState } from 'react';
import type { MemoryEstimate, MemoryInfo, MemoryUnit } from '@/services/api';
import type { TextExtractionUiStatus } from '@/hooks/useTextExtraction';
import CostEstimateDialog from './CostEstimateDialog';

interface MemoryTabProps {
  memory: MemoryInfo | null;
  loading: boolean;
  error: string | null;
  textStatus: TextExtractionUiStatus;
  currentPage: number;
  onJump: (page: number) => void;
  onFetchEstimate: (scope?: 'full') => Promise<MemoryEstimate>;
  onBuild: () => Promise<void>;
  onRebuild: () => Promise<void>;
  onCancel: () => Promise<void>;
  onOpenUnit: (unit: MemoryUnit) => void;
  onOpenBookSummary: () => void;
}

type PendingAction = 'build' | 'rebuild' | null;

export default function MemoryTab({
  memory,
  loading,
  error,
  textStatus,
  currentPage,
  onJump,
  onFetchEstimate,
  onBuild,
  onRebuild,
  onCancel,
  onOpenUnit,
  onOpenBookSummary,
}: MemoryTabProps) {
  const [estimate, setEstimate] = useState<MemoryEstimate | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // 当前单元 = 最后一个 start_page <= currentPage 的单元（与目录 Tab 同口径）
  const activeUnitId = useMemo(() => {
    let active: string | null = null;
    for (const u of memory?.units ?? []) {
      if (u.start_page <= currentPage) active = u.id;
    }
    return active;
  }, [memory, currentPage]);

  const openEstimate = async (action: Exclude<PendingAction, null>) => {
    setEstimateLoading(true);
    setActionError(null);
    try {
      // rebuild 清空重来，花费预估须强制走全书 scope，与实际行为对齐（build/继续加工保持自动 scope）。
      setEstimate(await onFetchEstimate(action === 'rebuild' ? 'full' : undefined));
      setPendingAction(action);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '花费预估获取失败');
    } finally {
      setEstimateLoading(false);
    }
  };

  const confirmAction = async () => {
    const action = pendingAction;
    setEstimate(null);
    setPendingAction(null);
    setActionError(null);
    try {
      if (action === 'build') await onBuild();
      else if (action === 'rebuild') await onRebuild();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '操作失败，可重试');
    }
  };

  const renderUnit = (u: MemoryUnit) => {
    const isActive = u.id === activeUnitId;
    return (
      <div key={u.id} className="px-1">
        <div
          className={`group flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer text-[12px] leading-snug transition-colors ${
            isActive
              ? 'bg-[#fef9f3] text-amber-700 border-l-2 border-amber-400'
              : 'text-stone-600 hover:bg-stone-200/40'
          }`}
          onClick={() => onOpenUnit(u)}
          title={`${u.title}（第 ${u.start_page}–${u.end_page} 页）`}
        >
          <i className="ri-file-text-line text-xs flex-shrink-0 text-stone-400" />
          <span className="flex-1 truncate">{u.title}</span>
          {u.status === 'failed' && (
            <i className="ri-error-warning-line text-red-400 flex-shrink-0" title={u.error ?? '加工失败'} />
          )}
          {u.status === 'pending' && (
            <i className="ri-time-line text-stone-300 flex-shrink-0" title="待加工" />
          )}
          <button
            onClick={(e) => {
              e.stopPropagation();
              onJump(u.start_page);
            }}
            className="text-[10px] flex-shrink-0 text-stone-400 hover:text-amber-600 cursor-pointer"
            title={`跳转到第 ${u.start_page} 页`}
          >
            {u.start_page}
          </button>
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-40 gap-2 text-stone-400">
        <i className="ri-loader-4-line animate-spin text-lg" />
        <span className="text-[10px]">加载记忆…</span>
      </div>
    );
  }

  if (error) {
    return <div className="px-3 py-4 text-[11px] text-stone-400">记忆状态加载失败：{error}</div>;
  }

  const status = memory?.status ?? 'none';

  // 空态 / 不可用态
  if (status === 'none' || status === 'failed') {
    const scanned = textStatus === 'unsupported';
    const textPending = !scanned && textStatus !== 'ok';
    return (
      <div className="px-3 py-4 text-[11px] text-stone-500 leading-relaxed space-y-3">
        {scanned ? (
          <p>扫描版 / 无文本层 PDF，记忆功能不可用。</p>
        ) : textPending ? (
          <p>等待全书文本提取完成后可建立记忆（见顶部状态条）。</p>
        ) : (
          <>
            <p>
              {status === 'failed'
                ? `记忆建立失败：${memory?.error ?? '未知错误'}`
                : '建立本书记忆：按章节生成要点总结与概念索引，随时回顾。'}
            </p>
            <button
              onClick={() => void openEstimate('build')}
              disabled={estimateLoading}
              className="px-2.5 py-1.5 text-[11px] rounded-md bg-amber-50 text-amber-700 hover:bg-amber-100 transition-colors cursor-pointer text-left disabled:opacity-50"
            >
              <i className="ri-sparkling-line mr-1" />
              {estimateLoading ? '获取花费预估…' : status === 'failed' ? '重试建立记忆' : '建立记忆'}
            </button>
            {actionError && <p className="text-red-400">{actionError}</p>}
          </>
        )}
        {estimate && (
          <CostEstimateDialog
            title="建立记忆 — 花费预估"
            model={estimate.model}
            inputTokens={estimate.estimated_input_tokens}
            outputTokens={estimate.estimated_output_tokens}
            cost={estimate.estimated_cost}
            confirmLabel="确认建立"
            onConfirm={() => void confirmAction()}
            onCancel={() => {
              setEstimate(null);
              setPendingAction(null);
            }}
          />
        )}
      </div>
    );
  }

  // running：进度 + 取消
  if (status === 'running') {
    const total = memory?.unit_total ?? 0;
    const done = memory?.unit_done ?? 0;
    const current = memory?.units.find((u) => u.status === 'pending');
    return (
      <div className="px-3 py-4 text-[11px] text-stone-500 space-y-3">
        <p>
          <i className="ri-loader-4-line animate-spin mr-1" />
          记忆加工中… {done}/{total}
        </p>
        <div className="h-1.5 rounded bg-stone-200 overflow-hidden">
          <div
            className="h-full bg-amber-400 transition-all"
            style={{ width: total > 0 ? `${(done / total) * 100}%` : '0%' }}
          />
        </div>
        {current && <p className="truncate text-stone-400">当前：{current.title}</p>}
        <button
          onClick={() => void onCancel()}
          className="text-[10px] text-stone-400 hover:text-stone-600 cursor-pointer"
        >
          取消（已完成章节保留）
        </button>
      </div>
    );
  }

  // partial / ready：产物列表
  const failedCount = (memory?.units ?? []).filter((u) => u.status !== 'ok').length;
  return (
    <div className="py-2">
      {memory?.toc_changed && (
        <div className="mx-2 mb-2 px-2 py-1.5 rounded bg-amber-50 border border-amber-200 text-[10px] text-amber-700 leading-relaxed">
          目录已变更，建议重建记忆（旧记忆仍可使用）。
        </div>
      )}
      {status === 'partial' && (
        <div className="mx-2 mb-2 px-2 py-1.5 rounded bg-stone-100 text-[10px] text-stone-500 leading-relaxed space-y-1">
          <p>{memory?.error ?? `${failedCount} 个章节未完成`}</p>
          <button
            onClick={() => void openEstimate('build')}
            disabled={estimateLoading}
            className="text-amber-600 hover:underline cursor-pointer disabled:opacity-50"
          >
            {estimateLoading ? '获取花费预估…' : '继续加工'}
          </button>
        </div>
      )}
      {memory?.book_summary && (
        <div className="mx-2 mb-2 rounded border border-amber-200/70 bg-[#fefaf4]">
          <button
            onClick={onOpenBookSummary}
            className="w-full flex items-center gap-1 px-2 py-1.5 text-[11px] text-amber-700 cursor-pointer"
          >
            <i className="ri-book-open-line" />
            全书总结
            <i className="ri-arrow-right-up-line ml-auto text-xs text-amber-400" />
          </button>
        </div>
      )}
      {(memory?.units ?? []).map(renderUnit)}
      <div className="mt-3 px-3">
        <button
          onClick={() => void openEstimate('rebuild')}
          disabled={estimateLoading}
          className="text-[10px] text-stone-400 hover:text-stone-600 cursor-pointer disabled:opacity-50"
          title="清空现有记忆并按当前目录重新加工"
        >
          <i className="ri-refresh-line mr-0.5" />
          重建记忆
        </button>
        {actionError && <p className="mt-1 text-[10px] text-red-400">{actionError}</p>}
      </div>
      {estimate && (
        <CostEstimateDialog
          title={pendingAction === 'rebuild' ? '重建记忆 — 花费预估' : '继续加工 — 花费预估'}
          model={estimate.model}
          inputTokens={estimate.estimated_input_tokens}
          outputTokens={estimate.estimated_output_tokens}
          cost={estimate.estimated_cost}
          confirmLabel={pendingAction === 'rebuild' ? '确认重建' : '确认继续'}
          onConfirm={() => void confirmAction()}
          onCancel={() => {
            setEstimate(null);
            setPendingAction(null);
          }}
        />
      )}
    </div>
  );
}

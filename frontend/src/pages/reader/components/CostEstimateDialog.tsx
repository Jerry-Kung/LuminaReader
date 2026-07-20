/**
 * V1.2.3 抽取：花费预估确认框（目录 LLM 识别与记忆加工两处共用，规格 §6.4 花费透明）。
 */
interface CostEstimateDialogProps {
  title: string;
  model: string;
  inputTokens: number;
  outputTokens?: number | null;
  cost: number | null;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function CostEstimateDialog({
  title,
  model,
  inputTokens,
  outputTokens,
  cost,
  confirmLabel,
  onConfirm,
  onCancel,
}: CostEstimateDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onCancel}>
      <div className="w-72 bg-white rounded-lg shadow-xl p-4 space-y-3" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-medium text-stone-700">{title}</h3>
        <div className="text-[11px] text-stone-500 space-y-1 leading-relaxed">
          <p>模型：{model}</p>
          <p>预计输入：约 {inputTokens.toLocaleString()} tokens</p>
          {outputTokens != null && <p>预计输出：约 {outputTokens.toLocaleString()} tokens</p>}
          <p>
            {cost != null
              ? `预计费用：约 $${cost.toFixed(4)}（估算，以账单为准）`
              : '该模型未在内置单价表中，请按 token 量自行估算费用'}
          </p>
        </div>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded-md text-stone-500 hover:bg-stone-100 cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded-md bg-amber-500 text-white hover:bg-amber-600 cursor-pointer"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

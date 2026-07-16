import { useEffect, useState } from 'react';
import type { TextExtractionUiStatus } from '../../../hooks/useTextExtraction';

interface TextExtractionBannerProps {
  pdfId: string;
  status: TextExtractionUiStatus;
  onTrigger: () => void;
}

function dismissKey(pdfId: string): string {
  return `lumina:textExtractionBannerDismissed:${pdfId}`;
}

/**
 * V1.2.1：全书文本提取状态条（工具栏下方）。
 * ok / loading / error 不渲染；unsupported 可关闭（sessionStorage 记忆，本次会话不再打扰）。
 */
export default function TextExtractionBanner({
  pdfId,
  status,
  onTrigger,
}: TextExtractionBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(sessionStorage.getItem(dismissKey(pdfId)) === '1');
  }, [pdfId]);

  if (status === 'ok' || status === 'loading' || status === 'error') return null;
  if (status === 'unsupported' && dismissed) return null;

  const handleDismiss = () => {
    sessionStorage.setItem(dismissKey(pdfId), '1');
    setDismissed(true);
  };

  if (status === 'pending') {
    return (
      <div className="flex items-center gap-2 px-4 py-1.5 bg-stone-50 border-b border-stone-200 text-xs text-stone-500">
        <i className="ri-loader-4-line animate-spin text-stone-400"></i>
        <span>正在提取全书文本……完成后 AI 可自动携带跨页上下文</span>
      </div>
    );
  }

  if (status === 'unsupported') {
    return (
      <div className="flex items-center gap-2 px-4 py-1.5 bg-stone-50 border-b border-stone-200 text-xs text-stone-500">
        <i className="ri-image-line text-stone-400"></i>
        <span>扫描版 / 无文本层 PDF：全书文本与记忆功能不可用（截图问答不受影响）</span>
        <button
          onClick={handleDismiss}
          className="ml-auto text-stone-400 hover:text-stone-600 cursor-pointer"
          title="本次会话不再提示"
        >
          <i className="ri-close-line"></i>
        </button>
      </div>
    );
  }

  // none / failed
  const isFailed = status === 'failed';
  return (
    <div
      className={`flex items-center gap-2 px-4 py-1.5 border-b text-xs ${
        isFailed
          ? 'bg-red-50 border-red-100 text-red-600'
          : 'bg-amber-50 border-amber-100 text-amber-700'
      }`}
    >
      <i className={isFailed ? 'ri-error-warning-line' : 'ri-book-open-line'}></i>
      <span>
        {isFailed
          ? '全书文本提取失败，可重试'
          : '本书尚未提取全书文本（跨页上下文与后续记忆功能的地基，本地完成、不产生费用）'}
      </span>
      <button
        onClick={onTrigger}
        className={`ml-auto whitespace-nowrap px-2.5 py-0.5 rounded font-medium cursor-pointer transition-colors ${
          isFailed
            ? 'bg-red-100 hover:bg-red-200 text-red-700'
            : 'bg-amber-100 hover:bg-amber-200 text-amber-800'
        }`}
      >
        {isFailed ? '重试' : '立即提取'}
      </button>
    </div>
  );
}

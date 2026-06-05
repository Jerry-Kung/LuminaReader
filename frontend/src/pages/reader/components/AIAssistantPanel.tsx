import { useState, useRef, useCallback, useEffect } from 'react';
import type { AIResult, Message, HistoryEntry } from '../page';
import type { TaskType, ErrorCategory } from '@/services/api';
import MarkdownRenderer from './MarkdownRenderer';

export type ChipPluginType = Extract<TaskType, 'translate' | 'explain' | 'dictionary'>;

export interface ChipStateItem {
  state: 'available' | 'disabled';
  reason?: string;
}

export type ChipsState = Record<ChipPluginType, ChipStateItem>;

interface AIAssistantPanelProps {
  results: AIResult[];
  history: HistoryEntry[];
  historyLoading: boolean;
  expandedHistoryId: string | null;
  onToggleHistory: (conversationId: string) => void;
  onHistoryFollowUp: (conversationId: string, text: string) => void;
  onDeleteHistory: (conversationId: string) => void;
  isAIWorking: boolean;
  error: string | null;
  hasSelection: boolean;
  activeTaskTypes: ChipPluginType[];
  userInput: string;
  panelMode: 'narrow' | 'wide' | 'overlay';
  chipsState: ChipsState;
  onFollowUp: (cardId: number, text: string) => void;
  onClearCard: (cardId: number) => void;
  onToggleCollapse: (cardId: number) => void;
  onAIRequest: (taskTypes: ChipPluginType[], userInput?: string) => void;
  onTaskTypeToggle: (type: ChipPluginType) => void;
  onUserInputChange: (text: string) => void;
  onPanelModeChange: (mode: 'narrow' | 'wide' | 'overlay') => void;
  onRetry?: (message: Message) => void;
  onDismissError?: (message: Message) => void;
  onToggleOcr?: (message: Message) => void;
}

const taskLabelConfig: Record<TaskType, { label: string; icon: string; bgClass: string; textClass: string }> = {
  translate: {
    label: '翻译',
    icon: 'ri-translate-2',
    bgClass: 'bg-amber-100',
    textClass: 'text-amber-700',
  },
  explain: {
    label: '解释',
    icon: 'ri-lightbulb-line',
    bgClass: 'bg-teal-50',
    textClass: 'text-teal-700',
  },
  dictionary: {
    label: '词典',
    icon: 'ri-book-open-line',
    bgClass: 'bg-violet-50',
    textClass: 'text-violet-700',
  },
  chat: {
    label: '对话',
    icon: 'ri-chat-3-line',
    bgClass: 'bg-stone-100',
    textClass: 'text-stone-600',
  },
  'screenshot-qa': {
    label: '截图问答',
    icon: 'ri-image-line',
    bgClass: 'bg-sky-50',
    textClass: 'text-sky-700',
  },
};

interface ChipColorClasses {
  selectedBg: string;
  selectedText: string;
  selectedBorder: string;
}

const chipColorMap: Record<ChipPluginType, ChipColorClasses> = {
  translate: {
    selectedBg: 'bg-amber-100',
    selectedText: 'text-amber-700',
    selectedBorder: 'border-amber-300',
  },
  explain: {
    selectedBg: 'bg-teal-50',
    selectedText: 'text-teal-700',
    selectedBorder: 'border-teal-300',
  },
  dictionary: {
    selectedBg: 'bg-violet-50',
    selectedText: 'text-violet-700',
    selectedBorder: 'border-violet-300',
  },
};

function formatRelativeFromEpochSec(epochSec: number): string {
  if (!epochSec) return '';
  const nowSec = Math.floor(Date.now() / 1000);
  const diff = Math.max(0, nowSec - epochSec);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 2) return '昨天';
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400 / 7)} 周前`;
  return `${Math.floor(diff / 86400 / 30)} 个月前`;
}

function categoryIcon(category?: ErrorCategory): string {
  switch (category) {
    case 'network':
      return 'ri-wifi-off-line';
    case 'timeout':
      return 'ri-time-line';
    case 'rate_limited':
      return 'ri-speed-up-line';
    case 'token_limit':
      return 'ri-text-wrap';
    case 'provider_unconfigured':
      return 'ri-shield-keyhole-line';
    default:
      return 'ri-error-warning-line';
  }
}

function OcrFoldable({
  text,
  collapsed,
  onToggle,
}: {
  text: string;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="mb-2 rounded-md border border-sky-100 bg-sky-50/60 overflow-hidden">
      <button
        onClick={onToggle}
        className="flex items-center justify-between w-full px-2 py-1.5 hover:bg-sky-100/50 transition-colors cursor-pointer"
        aria-expanded={!collapsed}
      >
        <span className="inline-flex items-center gap-1 text-[10px] font-medium text-sky-700">
          <i className="ri-scan-line text-[10px]"></i>
          识别文本
        </span>
        <i
          className={`ri-arrow-down-s-line text-sky-500 text-xs transition-transform duration-200 ${
            collapsed ? '' : 'rotate-180'
          }`}
        ></i>
      </button>
      {!collapsed && (
        <div className="px-2 pb-2 pt-1">
          <p className="text-[11px] text-sky-900/80 leading-relaxed whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
            {text || <span className="text-sky-400/70">（未提取到识别文本）</span>}
          </p>
        </div>
      )}
    </div>
  );
}

function MessageBubble({
  message,
  onRetry,
  onDismiss,
  onToggleOcr,
}: {
  message: Message;
  onRetry?: (m: Message) => void;
  onDismiss?: (m: Message) => void;
  onToggleOcr?: (m: Message) => void;
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end mb-2">
        <div className="max-w-[85%] max-w-[560px] bg-stone-200 rounded-2xl rounded-br-md px-3 py-2">
          <p className="text-sm text-stone-700 leading-relaxed whitespace-pre-wrap">{message.text}</p>
        </div>
      </div>
    );
  }

  if (message.isLoading) {
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[85%] max-w-[560px] bg-white border border-stone-200 rounded-2xl rounded-bl-md px-3 py-2.5">
          <div className="flex items-center gap-2 text-stone-400">
            <div className="w-5 h-5 flex items-center justify-center rounded-full bg-amber-100">
              <i className="ri-robot-2-line text-amber-600 text-xs"></i>
            </div>
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-stone-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
              <span className="w-1.5 h-1.5 bg-stone-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
              <span className="w-1.5 h-1.5 bg-stone-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (message.isError) {
    return (
      <div className="flex justify-start mb-2">
        <div className="max-w-[85%] max-w-[560px] bg-red-50 border border-red-200 rounded-2xl rounded-bl-md px-3 py-2.5">
          <div className="flex items-start gap-2">
            <i className={`${categoryIcon(message.errorCategory)} text-red-400 text-sm mt-0.5`}></i>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-red-600">{message.errorText || 'AI 调用失败'}</p>
              <div className="flex items-center gap-2 mt-2">
                {message.retry && onRetry && (
                  <button
                    onClick={() => onRetry(message)}
                    className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-red-600 bg-white border border-red-200 rounded-md hover:bg-red-100 cursor-pointer transition-colors"
                  >
                    <i className="ri-refresh-line text-xs mr-1"></i>
                    重试
                  </button>
                )}
                {onDismiss && (
                  <button
                    onClick={() => onDismiss(message)}
                    className="inline-flex items-center px-2.5 py-1 text-xs font-medium text-stone-500 bg-white border border-stone-200 rounded-md hover:bg-stone-50 cursor-pointer transition-colors"
                  >
                    忽略
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start mb-2">
      <div className="max-w-[85%] max-w-[560px] bg-white border border-stone-200 rounded-2xl rounded-bl-md px-3 py-2.5 overflow-hidden">
        <div className="flex items-center gap-1.5 mb-1">
          <div className="w-4 h-4 flex items-center justify-center rounded-full bg-amber-100">
            <i className="ri-robot-2-line text-amber-600 text-[10px]"></i>
          </div>
          <span className="text-[10px] text-stone-400 font-medium">AI</span>
        </div>
        {message.ocrText !== undefined && (
          <OcrFoldable
            text={message.ocrText}
            collapsed={message.ocrCollapsed === true}
            onToggle={() => onToggleOcr?.(message)}
          />
        )}
        <MarkdownRenderer content={message.text} />
      </div>
    </div>
  );
}

function FollowUpInput({ onSend, disabled }: { onSend: (text: string) => void; disabled: boolean }) {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (trimmed && !disabled) {
      onSend(trimmed);
      setText('');
    }
  }, [text, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isDisabled = disabled || !text.trim();

  return (
    <div className="flex items-start gap-1.5 mt-2 pt-2 border-t border-stone-100">
      <textarea
        ref={inputRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="继续追问…"
        disabled={disabled}
        className="flex-1 min-h-[32px] max-h-20 text-xs text-stone-700 bg-stone-50 border border-stone-200 rounded-lg px-2.5 py-1.5 resize-none focus:outline-none focus:border-amber-400 placeholder:text-stone-400 leading-relaxed"
        rows={1}
      />
      <button
        onClick={handleSend}
        disabled={isDisabled}
        className="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
        title="Send (Enter)"
      >
        <i className="ri-send-plane-fill text-xs"></i>
      </button>
    </div>
  );
}

function HistoryItem({
  entry,
  isExpanded,
  onToggle,
  onFollowUp,
  onDelete,
  isAIWorking,
  onRetry,
  onDismissError,
  onToggleOcr,
}: {
  entry: HistoryEntry;
  isExpanded: boolean;
  onToggle: () => void;
  onFollowUp: (text: string) => void;
  onDelete: () => void;
  isAIWorking: boolean;
  onRetry?: (m: Message) => void;
  onDismissError?: (m: Message) => void;
  onToggleOcr?: (m: Message) => void;
}) {
  const config = taskLabelConfig[entry.taskType];
  const placeholder = (entry.summary || '历史对话').slice(0, 60);
  const firstLetter = (entry.summary || '?').trim().charAt(0).toUpperCase() || '？';
  const hasLoading = entry.messages.some((m) => m.isLoading || m.isStreaming);

  return (
    <div className="rounded-lg border border-stone-200 bg-white overflow-hidden">
      <div className="flex items-stretch w-full hover:bg-stone-50/50 transition-colors">
        <button
          onClick={onToggle}
          className="flex items-center gap-3 flex-1 min-w-0 px-3 py-2.5 text-left cursor-pointer"
        >
          <div className="w-10 h-8 rounded border border-stone-200 flex-shrink-0 flex items-center justify-center bg-stone-100 text-stone-400">
            <span className="text-sm font-serif">{firstLetter}</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm text-stone-700 truncate leading-snug">{placeholder}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded-full ${config.bgClass} ${config.textClass}`}>
                <i className={`${config.icon} text-[10px]`}></i>
                {config.label}
              </span>
              <span className="text-xs text-stone-400">{formatRelativeFromEpochSec(entry.lastUsedAt)}</span>
            </div>
          </div>
          <i
            className={`ri-arrow-down-s-line text-stone-400 flex-shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
          ></i>
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="w-9 flex-shrink-0 flex items-center justify-center text-stone-400 hover:text-red-500 hover:bg-red-50 transition-colors cursor-pointer border-l border-stone-100"
          title="删除该历史对话"
          aria-label="删除该历史对话"
        >
          <i className="ri-delete-bin-line text-sm"></i>
        </button>
      </div>

      <div
        className={`transition-all duration-300 ease-out overflow-hidden ${isExpanded ? 'max-h-[3000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="px-3 pb-3 pt-2 border-t border-stone-100">
          {entry.loading && entry.messages.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-stone-400 py-2">
              <i className="ri-loader-4-line animate-spin"></i>
              加载历史对话…
            </div>
          ) : entry.loadError ? (
            <div className="text-xs text-red-500 py-2">{entry.loadError}</div>
          ) : (
            <>
              {entry.messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  onRetry={onRetry}
                  onDismiss={onDismissError}
                  onToggleOcr={onToggleOcr}
                />
              ))}
              {!hasLoading && (
                <FollowUpInput onSend={onFollowUp} disabled={isAIWorking} />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const CHIP_DEFS: { type: ChipPluginType; icon: string; label: string }[] = [
  { type: 'translate', icon: 'ri-translate-2', label: '翻译' },
  { type: 'explain', icon: 'ri-lightbulb-line', label: '解释' },
  { type: 'dictionary', icon: 'ri-book-open-line', label: '词典' },
];

function CapabilityChip({
  icon,
  label,
  isSelected,
  isDisabled,
  isFaded,
  disabledReason,
  colors,
  onClick,
}: {
  icon: string;
  label: string;
  isSelected: boolean;
  isDisabled: boolean;
  isFaded?: boolean;
  disabledReason?: string;
  colors: ChipColorClasses;
  onClick: () => void;
}) {
  const [showTooltip, setShowTooltip] = useState(false);

  const handleClick = () => {
    if (!isDisabled) onClick();
  };

  const reallyDisabled = isDisabled && !isFaded;

  return (
    <div
      className="relative"
      onMouseEnter={() => {
        if (isDisabled && disabledReason) setShowTooltip(true);
      }}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button
        onClick={handleClick}
        disabled={reallyDisabled}
        className={`whitespace-nowrap inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-full border transition-all duration-150 cursor-pointer ${
          isFaded
            ? 'border-stone-200/40 text-stone-300 bg-stone-50/60 opacity-50 hover:opacity-60'
            : isDisabled
              ? 'border-stone-200/50 text-stone-300 bg-stone-50/50 cursor-not-allowed'
              : isSelected
                ? `${colors.selectedBg} ${colors.selectedText} ${colors.selectedBorder}`
                : 'bg-white text-stone-500 border-stone-200 hover:border-stone-300 hover:text-stone-600'
        }`}
      >
        <i className={`${icon} text-xs`}></i>
        {label}
      </button>
      {showTooltip && isDisabled && disabledReason && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2 py-1 bg-stone-800 text-white text-[10px] rounded-md whitespace-nowrap shadow-lg z-30 pointer-events-none">
          {disabledReason}
          <div className="absolute top-full left-1/2 -translate-x-1/2 w-0 h-0 border-l-4 border-r-4 border-t-4 border-transparent border-t-stone-800"></div>
        </div>
      )}
    </div>
  );
}

function LaunchInputArea({
  hasSelection,
  activeTaskTypes,
  userInput,
  isAIWorking,
  chipsState,
  onAIRequest,
  onTaskTypeToggle,
  onUserInputChange,
}: {
  hasSelection: boolean;
  activeTaskTypes: ChipPluginType[];
  userInput: string;
  isAIWorking: boolean;
  chipsState: ChipsState;
  onAIRequest: (taskTypes: ChipPluginType[], userInput?: string) => void;
  onTaskTypeToggle: (type: ChipPluginType) => void;
  onUserInputChange: (text: string) => void;
}) {
  const trimmedInput = userInput.trim();
  const canSend = hasSelection && (activeTaskTypes.length > 0 || trimmedInput.length > 0);
  const sendDisabled = !canSend || isAIWorking;

  const handleSend = () => {
    if (sendDisabled) return;
    onAIRequest(activeTaskTypes, userInput);
    onUserInputChange('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-stone-100 p-4 bg-white">
      {!hasSelection && (
        <div className="flex items-center gap-2 text-stone-400 mb-2">
          <i className="ri-cursor-line text-xs"></i>
          <span className="text-xs">请先在 PDF 上框选一段内容</span>
        </div>
      )}
      <div className="space-y-2.5">
        <textarea
          value={userInput}
          onChange={(e) => onUserInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="想问点什么？或选择下方能力一键运行"
          disabled={isAIWorking}
          className="w-full h-[68px] text-sm text-stone-700 bg-stone-50 border border-stone-200 rounded-lg px-3 py-2.5 resize-none focus:outline-none focus:border-amber-400 placeholder:text-stone-400 leading-relaxed disabled:bg-stone-100 disabled:text-stone-400"
          rows={2}
        />
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            {CHIP_DEFS.map((chip) => {
              const cs = chipsState[chip.type];
              const chipUnavailable = cs?.state === 'disabled';
              const isSelected = activeTaskTypes.includes(chip.type);
              const colors = chipColorMap[chip.type];

              // 未框选时所有 chip 显示为浅淡 faded 态，可点击切换但视觉上提示主动作未就绪
              if (!hasSelection) {
                return (
                  <CapabilityChip
                    key={chip.type}
                    icon={chip.icon}
                    label={chip.label}
                    isSelected={isSelected}
                    isDisabled={false}
                    isFaded={true}
                    disabledReason={undefined}
                    colors={colors}
                    onClick={() => onTaskTypeToggle(chip.type)}
                  />
                );
              }

              return (
                <CapabilityChip
                  key={chip.type}
                  icon={chip.icon}
                  label={chip.label}
                  isSelected={isSelected}
                  isDisabled={chipUnavailable}
                  isFaded={false}
                  disabledReason={cs?.reason}
                  colors={colors}
                  onClick={() => onTaskTypeToggle(chip.type)}
                />
              );
            })}
          </div>
          <button
            onClick={handleSend}
            disabled={sendDisabled}
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer transition-colors"
            title="发送"
          >
            {isAIWorking ? (
              <i className="ri-loader-4-line animate-spin text-sm"></i>
            ) : (
              <i className="ri-arrow-up-line text-sm"></i>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

const modeIcons: Record<string, string> = {
  narrow: 'ri-expand-right-line',
  wide: 'ri-fullscreen-line',
  overlay: 'ri-fullscreen-exit-line',
};

const modeTooltips: Record<string, string> = {
  narrow: 'Switch to wide mode',
  wide: 'Switch to overlay mode',
  overlay: 'Back to narrow mode',
};

function getNextMode(mode: 'narrow' | 'wide' | 'overlay'): 'narrow' | 'wide' | 'overlay' {
  if (mode === 'narrow') return 'wide';
  if (mode === 'wide') return 'overlay';
  return 'narrow';
}

export default function AIAssistantPanel({
  results,
  history,
  historyLoading,
  expandedHistoryId,
  onToggleHistory,
  onHistoryFollowUp,
  onDeleteHistory,
  isAIWorking,
  error,
  hasSelection,
  activeTaskTypes,
  userInput,
  panelMode,
  chipsState,
  onFollowUp,
  onClearCard,
  onToggleCollapse,
  onAIRequest,
  onTaskTypeToggle,
  onUserInputChange,
  onPanelModeChange,
  onRetry,
  onDismissError,
  onToggleOcr,
}: AIAssistantPanelProps) {
  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback silently
    }
  };

  const handleCycleMode = () => {
    onPanelModeChange(getNextMode(panelMode));
  };

  const handleOverlayBackdropClick = () => {
    if (panelMode === 'overlay') {
      onPanelModeChange('narrow');
    }
  };

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const latestCardId = results.length > 0 ? results[results.length - 1].id : null;

  useEffect(() => {
    if (latestCardId === null) return;
    const node = scrollContainerRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [latestCardId]);

  const hasAnyCard = results.length > 0;
  const hasHistory = history.length > 0;

  const isOverlay = panelMode === 'overlay';
  const isWide = panelMode === 'wide';

  const widthClasses = isOverlay
    ? 'absolute right-0 top-0 bottom-0 z-20 shadow-2xl w-[85%]'
    : isWide
      ? 'w-[520px] flex-shrink-0'
      : 'w-[340px] flex-shrink-0';

  return (
    <>
      {isOverlay && (
        <div
          className="fixed inset-0 bg-black/15 z-10 transition-opacity duration-300"
          onClick={handleOverlayBackdropClick}
        />
      )}
      <div
        className={`flex flex-col bg-white border-l border-stone-200 transition-all duration-300 ease-out ${widthClasses}`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-stone-100 flex-shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 flex items-center justify-center rounded-lg bg-amber-100">
              <i className="ri-robot-2-line text-amber-600 text-sm"></i>
            </div>
            <h2 className="text-sm font-semibold text-stone-700">AI Assistant</h2>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={handleCycleMode}
              className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-200 transition-all cursor-pointer"
              title={modeTooltips[panelMode]}
            >
              <i className={`${modeIcons[panelMode]} text-sm`}></i>
            </button>
          </div>
        </div>

        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto p-4">
          {/* History Section */}
          <div className="mb-4">
            <div className="flex items-center gap-2 mb-2">
              <i className="ri-history-line text-stone-400 text-xs"></i>
              <span className="text-xs font-medium text-stone-400">历史对话</span>
              {historyLoading && (
                <i className="ri-loader-4-line animate-spin text-stone-300 text-xs"></i>
              )}
            </div>

            {hasHistory ? (
              <div className="space-y-2">
                {history.map((entry) => (
                  <HistoryItem
                    key={entry.conversationId}
                    entry={entry}
                    isExpanded={expandedHistoryId === entry.conversationId}
                    onToggle={() => onToggleHistory(entry.conversationId)}
                    onFollowUp={(text) => onHistoryFollowUp(entry.conversationId, text)}
                    onDelete={() => onDeleteHistory(entry.conversationId)}
                    isAIWorking={isAIWorking}
                    onRetry={onRetry}
                    onDismissError={onDismissError}
                    onToggleOcr={onToggleOcr}
                  />
                ))}
              </div>
            ) : (
              <p className="text-xs text-stone-300 py-2">
                {historyLoading ? '加载中…' : '还没有对话历史，框选 PDF 上的文字试试'}
              </p>
            )}
          </div>

          {/* Current session */}
          {isAIWorking && !hasAnyCard && (
            <div className="flex flex-col items-center justify-center gap-3 text-stone-400 py-6">
              <i className="ri-loader-4-line animate-spin text-2xl"></i>
              <p className="text-sm">AI 正在思考…</p>
            </div>
          )}

          {error && !hasAnyCard && (
            <div className="flex flex-col items-center gap-3 p-4 rounded-lg bg-red-50 border border-red-200">
              <i className="ri-error-warning-line text-red-400 text-xl"></i>
              <p className="text-sm text-red-600 text-center">{error}</p>
            </div>
          )}

          {!isAIWorking && !hasAnyCard && !hasHistory && (
            <div className="flex flex-col items-center justify-center gap-3 text-stone-300 py-6">
              <div className="w-14 h-14 flex items-center justify-center rounded-xl bg-stone-100">
                <i className="ri-robot-2-line text-2xl"></i>
              </div>
              <div className="text-center">
                <p className="text-sm text-stone-400">还没有对话</p>
                <p className="text-xs text-stone-300 mt-1">
                  在 PDF 上框选一段内容，然后在下方输入问题点击运行
                </p>
              </div>
            </div>
          )}

          {hasAnyCard && (
            <div className="space-y-4">
              {results.map((result) => {
                const config = taskLabelConfig[result.type];
                const aiMessages = result.messages.filter((m) => m.role === 'ai');
                const latestAiMessage = aiMessages[aiMessages.length - 1];
                const hasLoading = result.messages.some((m) => m.isLoading || m.isStreaming);

                return (
                  <div
                    key={result.id}
                    className="group rounded-lg border border-stone-200 bg-stone-50/50 overflow-hidden"
                  >
                    <div className="flex items-center justify-between px-3 py-2 bg-stone-100/70">
                      <div className="flex items-center gap-2">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${config.bgClass} ${config.textClass}`}
                        >
                          <i className={`${config.icon} text-xs`}></i>
                          {config.label}
                        </span>
                        <span className="text-xs text-stone-400">
                          {new Date(result.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        {latestAiMessage && !latestAiMessage.isLoading && !latestAiMessage.isError && (
                          <button
                            onClick={() => handleCopy(latestAiMessage.text)}
                            className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-200 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                            title="Copy latest AI response"
                          >
                            <i className="ri-file-copy-line text-sm"></i>
                          </button>
                        )}
                        <button
                          onClick={() => onToggleCollapse(result.id)}
                          className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-200 transition-all cursor-pointer"
                          title={result.collapsed ? 'Expand card' : 'Collapse card'}
                        >
                          <i
                            className={`${
                              result.collapsed ? 'ri-arrow-down-s-line' : 'ri-arrow-up-s-line'
                            } text-sm`}
                          ></i>
                        </button>
                        <button
                          onClick={() => onClearCard(result.id)}
                          className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                          title="Clear conversation"
                        >
                          <i className="ri-delete-bin-line text-sm"></i>
                        </button>
                      </div>
                    </div>

                    {!result.collapsed && (
                      <>
                        <div className="px-3 pt-2">
                          <img
                            src={result.imageBase64}
                            alt="Selected area"
                            className="w-14 h-14 object-cover rounded-md border border-stone-200"
                          />
                        </div>

                        <div className="px-2 py-2">
                          {result.messages.map((message) => (
                            <MessageBubble
                              key={message.id}
                              message={message}
                              onRetry={onRetry}
                              onDismiss={onDismissError}
                              onToggleOcr={onToggleOcr}
                            />
                          ))}
                        </div>

                        {!hasLoading && (
                          <div className="px-3 pb-3">
                            <FollowUpInput
                              onSend={(text) => onFollowUp(result.id, text)}
                              disabled={isAIWorking}
                            />
                          </div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex-shrink-0">
          <LaunchInputArea
            hasSelection={hasSelection}
            activeTaskTypes={activeTaskTypes}
            userInput={userInput}
            isAIWorking={isAIWorking}
            chipsState={chipsState}
            onAIRequest={onAIRequest}
            onTaskTypeToggle={onTaskTypeToggle}
            onUserInputChange={onUserInputChange}
          />
        </div>
      </div>
    </>
  );
}

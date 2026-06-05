import { useState, useRef, useCallback } from 'react';
import type { AIResult, Message } from '../page';
import type { TaskType, HistoryConversation } from '@/services/api';
import MarkdownRenderer from './MarkdownRenderer';

interface ChipStateItem {
  state: 'available' | 'disabled';
  reason?: string;
}

interface AIAssistantPanelProps {
  results: AIResult[];
  historyConversations: HistoryConversation[];
  historyLoading: boolean;
  isAIWorking: boolean;
  error: string | null;
  hasSelection: boolean;
  activeTaskTypes: TaskType[];
  userInput: string;
  panelMode: 'narrow' | 'wide' | 'overlay';
  chipsState: Record<string, ChipStateItem>;
  onFollowUp: (cardId: number, text: string) => void;
  onClearCard: (cardId: number) => void;
  onAIRequest: (taskTypes: TaskType[], userInput?: string) => void;
  onTaskTypeToggle: (type: TaskType) => void;
  onUserInputChange: (text: string) => void;
  onPanelModeChange: (mode: 'narrow' | 'wide' | 'overlay') => void;
  onHistoryFollowUp: (historyId: number, text: string) => void;
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
};

interface ChipColorClasses {
  selectedBg: string;
  selectedText: string;
  selectedBorder: string;
}

const chipColorMap: Record<string, ChipColorClasses> = {
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

function getRelativeTime(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return '刚刚';
  if (diffMins < 60) return `${diffMins} 分钟前`;
  if (diffHours < 24) return `${diffHours} 小时前`;
  if (diffDays === 1) return '昨天';
  if (diffDays < 7) return `${diffDays} 天前`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)} 周前`;
  return `${Math.floor(diffDays / 30)} 个月前`;
}

function MessageBubble({ message }: { message: Message }) {
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
            <i className="ri-error-warning-line text-red-400 text-sm mt-0.5"></i>
            <div>
              <p className="text-sm text-red-600">{message.errorText || 'Request failed'}</p>
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
        placeholder="Ask a follow-up..."
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
  history,
  isExpanded,
  onToggle,
  onFollowUp,
  isAIWorking,
}: {
  history: HistoryConversation;
  isExpanded: boolean;
  onToggle: () => void;
  onFollowUp: (text: string) => void;
  isAIWorking: boolean;
}) {
  const hasLoading = history.messages.some((m) => m.isLoading);
  const config = taskLabelConfig[history.type];

  return (
    <div className="rounded-lg border border-stone-200 bg-white overflow-hidden">
      {/* Collapsed header */}
      <button
        onClick={onToggle}
        className="flex items-center gap-3 w-full px-3 py-2.5 text-left cursor-pointer hover:bg-stone-50/50 transition-colors"
      >
        <img
          src={history.thumbnail}
          alt="Selection"
          className="w-10 h-8 object-cover rounded border border-stone-200 flex-shrink-0"
        />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-stone-700 truncate leading-snug">{history.first_question}</p>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded-full ${config.bgClass} ${config.textClass}`}>
              <i className={`${config.icon} text-[10px]`}></i>
              {config.label}
            </span>
            <span className="text-xs text-stone-400">{getRelativeTime(history.updated_at)}</span>
          </div>
        </div>
        <i
          className={`ri-arrow-down-s-line text-stone-400 flex-shrink-0 transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`}
        ></i>
      </button>

      {/* Expanded content */}
      <div
        className={`transition-all duration-300 ease-out overflow-hidden ${isExpanded ? 'max-h-[3000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="px-3 pb-3 pt-2 border-t border-stone-100">
          {history.messages.map((message) => (
            <MessageBubble key={message.id} message={message as Message} />
          ))}
          {!hasLoading && (
            <FollowUpInput onSend={onFollowUp} disabled={isAIWorking} />
          )}
        </div>
      </div>
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
  activeTaskTypes: TaskType[];
  userInput: string;
  isAIWorking: boolean;
  chipsState: Record<string, ChipStateItem>;
  onAIRequest: (taskTypes: TaskType[], userInput?: string) => void;
  onTaskTypeToggle: (type: TaskType) => void;
  onUserInputChange: (text: string) => void;
}) {
  const handleSend = () => {
    onAIRequest(activeTaskTypes, userInput);
    onUserInputChange('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const canSend = activeTaskTypes.length > 0 || userInput.trim().length > 0;
      if (canSend && !isAIWorking) {
        handleSend();
      }
    }
  };

  const canSend = hasSelection && (activeTaskTypes.length > 0 || userInput.trim().length > 0);
  const sendDisabled = !canSend || isAIWorking;

  const chips: { type: TaskType; icon: string; label: string }[] = [
    { type: 'translate', icon: 'ri-translate-2', label: '翻译' },
    { type: 'explain', icon: 'ri-lightbulb-line', label: '解释' },
    { type: 'dictionary', icon: 'ri-book-open-line', label: '词典' },
  ];

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
            {chips.map((chip) => {
              const cs = chipsState[chip.type];
              const chipUnavailable = cs?.state === 'disabled';
              const isSelected = activeTaskTypes.includes(chip.type);
              const colors = chipColorMap[chip.type];

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
  historyConversations,
  historyLoading,
  isAIWorking,
  error,
  hasSelection,
  activeTaskTypes,
  userInput,
  panelMode,
  chipsState,
  onFollowUp,
  onClearCard,
  onAIRequest,
  onTaskTypeToggle,
  onUserInputChange,
  onPanelModeChange,
  onHistoryFollowUp,
}: AIAssistantPanelProps) {
  const [expandedHistoryId, setExpandedHistoryId] = useState<number | null>(null);

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

  const handleToggleHistory = (historyId: number) => {
    setExpandedHistoryId((prev) => (prev === historyId ? null : historyId));
  };

  const hasAnyCard = results.length > 0;
  const hasHistory = historyConversations.length > 0;

  const isOverlay = panelMode === 'overlay';
  const isWide = panelMode === 'wide';
  const isNarrow = panelMode === 'narrow';

  const widthClasses = isOverlay
    ? 'absolute right-0 top-0 bottom-0 z-20 shadow-2xl w-[85%]'
    : isWide
      ? 'w-[520px] flex-shrink-0'
      : 'w-[340px] flex-shrink-0';

  return (
    <>
      {/* Overlay backdrop */}
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

        <div className="flex-1 overflow-y-auto p-4">
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
                {historyConversations.map((history) => (
                  <HistoryItem
                    key={history.id}
                    history={history}
                    isExpanded={expandedHistoryId === history.id}
                    onToggle={() => handleToggleHistory(history.id)}
                    onFollowUp={(text) => onHistoryFollowUp(history.id, text)}
                    isAIWorking={isAIWorking}
                  />
                ))}
              </div>
            ) : (
              <p className="text-xs text-stone-300 py-2">
                {historyLoading ? 'Loading...' : '还没有对话历史，框选 PDF 上的文字试试'}
              </p>
            )}
          </div>

          {/* Current session */}
          {isAIWorking && !hasAnyCard && (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-stone-400">
              <i className="ri-loader-4-line animate-spin text-2xl"></i>
              <p className="text-sm">AI is working...</p>
            </div>
          )}

          {error && !hasAnyCard && (
            <div className="flex flex-col items-center gap-3 p-4 rounded-lg bg-red-50 border border-red-200">
              <i className="ri-error-warning-line text-red-400 text-xl"></i>
              <p className="text-sm text-red-600 text-center">{error}</p>
            </div>
          )}

          {!isAIWorking && !hasAnyCard && !hasHistory && (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-stone-300">
              <div className="w-14 h-14 flex items-center justify-center rounded-xl bg-stone-100">
                <i className="ri-robot-2-line text-2xl"></i>
              </div>
              <div className="text-center">
                <p className="text-sm text-stone-400">No AI conversations yet</p>
                <p className="text-xs text-stone-300 mt-1">
                  Select an area on the PDF, then type a question below and click Run
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
                const hasLoading = result.messages.some((m) => m.isLoading);

                return (
                  <div
                    key={result.id}
                    className="group rounded-lg border border-stone-200 bg-stone-50/50 overflow-hidden"
                  >
                    {/* Card header */}
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
                          onClick={() => onClearCard(result.id)}
                          className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                          title="Clear conversation"
                        >
                          <i className="ri-delete-bin-line text-sm"></i>
                        </button>
                      </div>
                    </div>

                    {/* Screenshot thumbnail */}
                    <div className="px-3 pt-2">
                      <img
                        src={result.imageBase64}
                        alt="Selected area"
                        className="w-14 h-14 object-cover rounded-md border border-stone-200"
                      />
                    </div>

                    {/* Message bubbles */}
                    <div className="px-2 py-2">
                      {result.messages.map((message) => (
                        <MessageBubble key={message.id} message={message} />
                      ))}
                    </div>

                    {/* Follow-up input */}
                    {!hasLoading && (
                      <div className="px-3 pb-3">
                        <FollowUpInput
                          onSend={(text) => onFollowUp(result.id, text)}
                          disabled={isAIWorking}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Bottom launch area */}
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
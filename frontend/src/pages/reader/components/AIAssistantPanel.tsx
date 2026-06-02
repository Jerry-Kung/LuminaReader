import { useState, useRef, useCallback, useEffect } from 'react';
import type { AIResult, Message, HistoryEntry } from '../page';
import type { TaskType } from '@/services/api';
import MarkdownRenderer from './MarkdownRenderer';

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
  activeTaskType: TaskType;
  userInput: string;
  panelMode: 'narrow' | 'wide' | 'overlay';
  onFollowUp: (cardId: number, text: string) => void;
  onClearCard: (cardId: number) => void;
  onToggleCollapse: (cardId: number) => void;
  onAIRequest: (taskType: TaskType, userInput?: string) => void;
  onTaskTypeChange: (type: TaskType) => void;
  onUserInputChange: (text: string) => void;
  onPanelModeChange: (mode: 'narrow' | 'wide' | 'overlay') => void;
}

const taskLabelConfig = {
  translate: {
    label: 'Translate',
    icon: 'ri-translate-2',
    bgClass: 'bg-amber-100',
    textClass: 'text-amber-700',
  },
  explain: {
    label: 'Explain',
    icon: 'ri-lightbulb-line',
    bgClass: 'bg-teal-50',
    textClass: 'text-teal-700',
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
  entry,
  isExpanded,
  onToggle,
  onFollowUp,
  onDelete,
  isAIWorking,
}: {
  entry: HistoryEntry;
  isExpanded: boolean;
  onToggle: () => void;
  onFollowUp: (text: string) => void;
  onDelete: () => void;
  isAIWorking: boolean;
}) {
  const config = taskLabelConfig[entry.taskType];
  const placeholder = (entry.summary || '历史对话').slice(0, 60);
  const firstLetter = (entry.summary || '?').trim().charAt(0).toUpperCase() || '？';
  const hasLoading = entry.messages.some((m) => m.isLoading);

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
                <MessageBubble key={message.id} message={message} />
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

function LaunchInputArea({
  hasSelection,
  activeTaskType,
  userInput,
  isAIWorking,
  onAIRequest,
  onTaskTypeChange,
  onUserInputChange,
}: {
  hasSelection: boolean;
  activeTaskType: TaskType;
  userInput: string;
  isAIWorking: boolean;
  onAIRequest: (taskType: TaskType, userInput?: string) => void;
  onTaskTypeChange: (type: TaskType) => void;
  onUserInputChange: (text: string) => void;
}) {
  const handleRun = () => {
    onAIRequest(activeTaskType, userInput);
    onUserInputChange('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (hasSelection && !isAIWorking) {
        handleRun();
      }
    }
  };

  const isDisabled = !hasSelection || isAIWorking;

  return (
    <div className="border-t border-stone-100 p-4 bg-white">
      {!hasSelection && (
        <div className="flex items-center gap-2 text-stone-400 mb-2">
          <i className="ri-cursor-line text-xs"></i>
          <span className="text-xs">Select an area on the PDF to start</span>
        </div>
      )}
      <div className="space-y-2">
        <textarea
          value={userInput}
          onChange={(e) => onUserInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask something optional (e.g. explain this formula, translate this paragraph)..."
          disabled={isDisabled}
          className="w-full h-20 text-sm text-stone-700 bg-stone-50 border border-stone-200 rounded-lg px-3 py-2.5 resize-none focus:outline-none focus:border-amber-400 placeholder:text-stone-400 leading-relaxed disabled:bg-stone-100 disabled:text-stone-400"
          rows={2}
        />
        <div className="flex items-center justify-between">
          <div className="flex items-center bg-stone-100 rounded-md p-0.5">
            <button
              onClick={() => onTaskTypeChange('translate')}
              disabled={isDisabled}
              className={`whitespace-nowrap px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                activeTaskType === 'translate'
                  ? 'bg-white text-amber-700 shadow-sm'
                  : 'text-stone-500 hover:text-stone-700'
              }`}
            >
              Translate
            </button>
            <button
              onClick={() => onTaskTypeChange('explain')}
              disabled={isDisabled}
              className={`whitespace-nowrap px-3 py-1.5 text-xs font-medium rounded-md transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                activeTaskType === 'explain'
                  ? 'bg-white text-teal-700 shadow-sm'
                  : 'text-stone-500 hover:text-stone-700'
              }`}
            >
              Explain
            </button>
          </div>
          <button
            onClick={handleRun}
            disabled={isDisabled}
            className="whitespace-nowrap flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-md hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
          >
            {isAIWorking ? (
              <>
                <i className="ri-loader-4-line animate-spin"></i>
                {activeTaskType === 'translate' ? 'Translating...' : 'Explaining...'}
              </>
            ) : (
              <>
                <i className="ri-sparkling-line"></i>
                Run
              </>
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
  activeTaskType,
  userInput,
  panelMode,
  onFollowUp,
  onClearCard,
  onToggleCollapse,
  onAIRequest,
  onTaskTypeChange,
  onUserInputChange,
  onPanelModeChange,
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
            <div className="flex flex-col items-center justify-center gap-3 text-stone-300 py-6">
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
                            <MessageBubble key={message.id} message={message} />
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
            activeTaskType={activeTaskType}
            userInput={userInput}
            isAIWorking={isAIWorking}
            onAIRequest={onAIRequest}
            onTaskTypeChange={onTaskTypeChange}
            onUserInputChange={onUserInputChange}
          />
        </div>
      </div>
    </>
  );
}

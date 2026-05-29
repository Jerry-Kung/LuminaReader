interface AIResult {
  id: number;
  type: 'translate';
  imageBase64: string;
  text: string;
  timestamp: number;
}

interface AIAssistantPanelProps {
  results: AIResult[];
  isTranslating: boolean;
  error: string | null;
}

export default function AIAssistantPanel({ results, isTranslating, error }: AIAssistantPanelProps) {
  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback silently
    }
  };

  return (
    <div className="w-[340px] flex-shrink-0 flex flex-col bg-white border-l border-stone-200">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-stone-100">
        <div className="w-7 h-7 flex items-center justify-center rounded-lg bg-amber-100">
          <i className="ri-robot-2-line text-amber-600 text-sm"></i>
        </div>
        <h2 className="text-sm font-semibold text-stone-700">AI Assistant</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {isTranslating && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-stone-400">
            <i className="ri-loader-4-line animate-spin text-2xl"></i>
            <p className="text-sm">Translating...</p>
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center gap-3 p-4 rounded-lg bg-red-50 border border-red-200">
            <i className="ri-error-warning-line text-red-400 text-xl"></i>
            <p className="text-sm text-red-600 text-center">{error}</p>
          </div>
        )}

        {!isTranslating && !error && results.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-stone-300">
            <div className="w-14 h-14 flex items-center justify-center rounded-xl bg-stone-100">
              <i className="ri-robot-2-line text-2xl"></i>
            </div>
            <div className="text-center">
              <p className="text-sm text-stone-400">No AI conversations yet</p>
              <p className="text-xs text-stone-300 mt-1">
                Select an area and click Translate to start
              </p>
            </div>
          </div>
        )}

        {!isTranslating && !error && results.length > 0 && (
          <div className="space-y-3">
            {results.map((result) => (
              <div
                key={result.id}
                className="group rounded-lg border border-stone-200 bg-stone-50/50 overflow-hidden"
              >
                <div className="flex items-center justify-between px-3 py-2 bg-stone-100/70">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-amber-700 bg-amber-100 rounded-full">
                      <i className="ri-translate-2 text-xs"></i>
                      Translate
                    </span>
                    <span className="text-xs text-stone-400">
                      {new Date(result.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <button
                    onClick={() => handleCopy(result.text)}
                    className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-200 opacity-0 group-hover:opacity-100 transition-all cursor-pointer"
                    title="Copy"
                  >
                    <i className="ri-file-copy-line text-sm"></i>
                  </button>
                </div>
                <div className="px-3 py-3 flex items-start gap-3">
                  <img
                    src={result.imageBase64}
                    alt="Selected area"
                    className="w-16 h-16 object-cover rounded-md border border-stone-200 flex-shrink-0"
                  />
                  <p className="text-sm text-stone-700 leading-relaxed whitespace-pre-wrap flex-1 min-w-0">
                    {result.text}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

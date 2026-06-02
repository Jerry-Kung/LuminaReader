interface OnboardingBannerProps {
  onDismiss: () => void;
}

const STEPS = [
  { icon: 'ri-upload-cloud-line', label: '上传 PDF', detail: '点击右上角上传，或把文件拖到书架' },
  { icon: 'ri-crop-line', label: '框选内容', detail: '打开一本书，按住鼠标在页面上拉出一个矩形' },
  { icon: 'ri-translate-2', label: '让 AI 翻译 / 解释', detail: '在右侧助手选择 Translate 或 Explain，点击 Run' },
  { icon: 'ri-question-answer-line', label: '继续追问', detail: '在卡片底部继续输入问题，AI 会基于当前选区回答' },
];

export default function OnboardingBanner({ onDismiss }: OnboardingBannerProps) {
  return (
    <div className="relative rounded-xl border border-amber-200 bg-amber-50/60 px-5 py-4 mb-4">
      <button
        onClick={onDismiss}
        className="absolute right-3 top-3 w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-amber-100 cursor-pointer"
        title="我已经熟悉了，关闭引导"
        aria-label="关闭引导"
      >
        <i className="ri-close-line text-sm"></i>
      </button>
      <div className="flex items-center gap-2 mb-3">
        <i className="ri-compass-3-line text-amber-600"></i>
        <h2 className="text-sm font-medium text-stone-700">第一次使用 LuminaReader？跟着这四步走一遍</h2>
      </div>
      <ol className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {STEPS.map((s, idx) => (
          <li key={s.label} className="flex items-start gap-2 rounded-lg bg-white border border-amber-100 px-3 py-2">
            <div className="w-7 h-7 flex-shrink-0 flex items-center justify-center rounded-full bg-amber-100 text-amber-700">
              <i className={`${s.icon} text-sm`}></i>
            </div>
            <div className="min-w-0">
              <p className="text-xs font-medium text-stone-700">
                <span className="text-amber-600 mr-1">{idx + 1}.</span>
                {s.label}
              </p>
              <p className="text-[11px] text-stone-500 leading-snug mt-0.5">{s.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

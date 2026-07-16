import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  getSettings,
  saveSettings,
  type ApiKeyIntent,
  type SettingsFieldError,
  type SettingsSource,
  type SettingsUpdateInput,
} from '@/services/api';
import {
  TextInput,
  NumberInput,
  PasswordInput,
  SettingsSection,
  StatusIndicator,
  Toast,
} from './components';

interface FormState {
  base_url: string;
  api_key: string;
  default_model: string;
  timeout_seconds: number;
  extract_model: string;
  translate_model: string;
  explain_model: string;
  thinking_enabled: boolean;
  context_expansion_enabled: boolean;
}

interface FormErrors {
  base_url: string | null;
  default_model: string | null;
  timeout_seconds: string | null;
}

function isValidUrl(url: string): boolean {
  if (!url) return false;
  return url.startsWith('http://') || url.startsWith('https://');
}

function deriveApiKeyIntent(current: string, originalMask: string | null): ApiKeyIntent {
  if (originalMask !== null && current === originalMask) {
    return { kind: 'keep' };
  }
  if (current === '') {
    if (originalMask === null) return { kind: 'keep' };
    return { kind: 'clear' };
  }
  if (originalMask !== null && current === originalMask) {
    return { kind: 'keep' };
  }
  return { kind: 'replace', value: current };
}

function mapFieldErrorsToFormErrors(
  fieldErrors: SettingsFieldError[],
): Partial<FormErrors> {
  const out: Partial<FormErrors> = {};
  for (const fe of fieldErrors) {
    if (fe.path === 'provider.base_url') out.base_url = fe.reason;
    else if (fe.path === 'provider.default_model') out.default_model = fe.reason;
    else if (fe.path === 'provider.timeout_seconds') out.timeout_seconds = fe.reason;
  }
  return out;
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [originalSettings, setOriginalSettings] = useState<SettingsSource | null>(null);
  const [form, setForm] = useState<FormState>({
    base_url: '',
    api_key: '',
    default_model: '',
    timeout_seconds: 60,
    extract_model: '',
    translate_model: '',
    explain_model: '',
    thinking_enabled: false,
    context_expansion_enabled: true,
  });
  const [errors, setErrors] = useState<FormErrors>({
    base_url: null,
    default_model: null,
    timeout_seconds: null,
  });
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'success' | 'error'>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [showEnvHint, setShowEnvHint] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [hasChanges, setHasChanges] = useState(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const [pendingNav, setPendingNav] = useState<string | null>(null);

  const backTo = location.state?.from || '/';

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await getSettings();
      setOriginalSettings(data);
      setForm({
        base_url: data.provider.base_url,
        api_key: data.provider.api_key_masked ?? '',
        default_model: data.provider.default_model,
        timeout_seconds: data.provider.timeout_seconds,
        extract_model: data.task_models.extract ?? '',
        translate_model: data.task_models.translate ?? '',
        explain_model: data.task_models.explain ?? '',
        thinking_enabled: data.thinking?.enabled ?? false,
        context_expansion_enabled: data.context_expansion?.enabled ?? true,
      });
      if (data.source === 'env_fallback') {
        setShowEnvHint(true);
      }
    } catch {
      setToast('Failed to load settings');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  useEffect(() => {
    if (!originalSettings) return;
    const originalMask = originalSettings.provider.api_key_masked ?? '';
    const keyChanged =
      originalMask === ''
        ? form.api_key !== ''
        : form.api_key !== originalMask;
    const otherChanged =
      form.base_url !== originalSettings.provider.base_url ||
      form.default_model !== originalSettings.provider.default_model ||
      form.timeout_seconds !== originalSettings.provider.timeout_seconds ||
      form.extract_model !== (originalSettings.task_models.extract ?? '') ||
      form.translate_model !== (originalSettings.task_models.translate ?? '') ||
      form.explain_model !== (originalSettings.task_models.explain ?? '') ||
      form.thinking_enabled !== (originalSettings.thinking?.enabled ?? false) ||
      form.context_expansion_enabled !==
        (originalSettings.context_expansion?.enabled ?? true);
    setHasChanges(keyChanged || otherChanged);
  }, [form, originalSettings]);

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const updateField = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (key === 'base_url') {
      setErrors((prev) => ({ ...prev, base_url: null }));
    }
    if (key === 'default_model') {
      setErrors((prev) => ({ ...prev, default_model: null }));
    }
    if (key === 'timeout_seconds') {
      setErrors((prev) => ({ ...prev, timeout_seconds: null }));
    }
  }, []);

  const validateField = useCallback((key: keyof FormState) => {
    if (key === 'base_url') {
      if (!isValidUrl(form.base_url)) {
        setErrors((prev) => ({ ...prev, base_url: '请输入合法的 http(s) 地址' }));
      } else {
        setErrors((prev) => ({ ...prev, base_url: null }));
      }
    }
    if (key === 'timeout_seconds') {
      if (form.timeout_seconds < 5 || form.timeout_seconds > 300) {
        setErrors((prev) => ({ ...prev, timeout_seconds: '超时秒数应在 5 到 300 之间' }));
      } else {
        setErrors((prev) => ({ ...prev, timeout_seconds: null }));
      }
    }
    if (key === 'default_model') {
      if (!form.default_model.trim()) {
        setErrors((prev) => ({ ...prev, default_model: '默认模型不能为空' }));
      } else {
        setErrors((prev) => ({ ...prev, default_model: null }));
      }
    }
  }, [form]);

  const handleSave = useCallback(async () => {
    const newErrors: FormErrors = {
      base_url: !isValidUrl(form.base_url) ? '请输入合法的 http(s) 地址' : null,
      default_model: !form.default_model.trim() ? '默认模型不能为空' : null,
      timeout_seconds:
        form.timeout_seconds < 5 || form.timeout_seconds > 300
          ? '超时秒数应在 5 到 300 之间'
          : null,
    };
    setErrors(newErrors);

    if (newErrors.base_url || newErrors.default_model || newErrors.timeout_seconds) {
      return;
    }

    setSaveState('saving');
    setSaveError(null);

    const intent = deriveApiKeyIntent(
      form.api_key,
      originalSettings?.provider.api_key_masked ?? null,
    );

    const input: SettingsUpdateInput = {
      base_url: form.base_url.trim(),
      default_model: form.default_model.trim(),
      timeout_seconds: form.timeout_seconds,
      task_models: {
        extract: form.extract_model.trim() || null,
        translate: form.translate_model.trim() || null,
        explain: form.explain_model.trim() || null,
      },
      thinking: {
        enabled: form.thinking_enabled,
      },
      context_expansion: {
        enabled: form.context_expansion_enabled,
      },
      api_key: intent,
    };

    const result = await saveSettings(input);

    switch (result.kind) {
      case 'ok': {
        setSaveState('success');
        showToast('Settings saved');
        setHasChanges(false);
        setOriginalSettings(result.data);
        setForm((prev) => ({
          ...prev,
          api_key: result.data.provider.api_key_masked ?? '',
        }));
        if (result.data.source === 'user_data') {
          setShowEnvHint(false);
        }
        setTimeout(() => setSaveState('idle'), 2000);
        break;
      }
      case 'invalid': {
        setSaveState('error');
        setSaveError(result.message);
        const mapped = mapFieldErrorsToFormErrors(result.fieldErrors);
        setErrors((prev) => ({ ...prev, ...mapped }));
        break;
      }
      case 'persist_failed': {
        setSaveState('error');
        setSaveError(result.message || '无法写入配置文件，请检查应用数据目录的写权限');
        break;
      }
      case 'network_error': {
        setSaveState('error');
        setSaveError(result.message || '无法连接后端，请检查后端服务是否启动');
        break;
      }
      case 'unknown_error': {
        setSaveState('error');
        setSaveError(result.message || `保存失败 (HTTP ${result.httpStatus ?? '?'})`);
        break;
      }
    }
  }, [form, originalSettings, showToast]);

  const handleCancel = useCallback(() => {
    if (hasChanges) {
      setShowLeaveConfirm(true);
      setPendingNav(backTo);
    } else {
      navigate(backTo);
    }
  }, [hasChanges, navigate, backTo]);

  const handleConfirmLeave = useCallback(() => {
    setShowLeaveConfirm(false);
    if (pendingNav) {
      navigate(pendingNav);
    }
  }, [pendingNav, navigate]);

  const handleStay = useCallback(() => {
    setShowLeaveConfirm(false);
    setPendingNav(null);
  }, []);

  const handleClearKey = useCallback(() => {
    setForm((prev) => ({ ...prev, api_key: '' }));
  }, []);

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasChanges]);

  const isSaving = saveState === 'saving';
  const isSuccess = saveState === 'success';

  return (
    <div className="min-h-screen bg-stone-50 flex flex-col">
      {/* Header */}
      <div className="bg-white border-b border-stone-200">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 flex items-center justify-center rounded-lg bg-amber-100">
              <i className="ri-settings-3-line text-amber-600 text-sm"></i>
            </div>
            <h1 className="text-lg font-semibold text-stone-700">Settings</h1>
          </div>
          <button
            onClick={handleCancel}
            className="w-8 h-8 flex items-center justify-center rounded-md text-stone-400 hover:text-stone-600 hover:bg-stone-100 cursor-pointer transition-colors"
          >
            <i className="ri-close-line text-sm"></i>
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 max-w-3xl mx-auto w-full px-6 py-6">
        {isLoading && (
          <div className="space-y-6">
            <div className="bg-white rounded-xl border border-stone-200 h-48 animate-pulse" />
            <div className="bg-white rounded-xl border border-stone-200 h-40 animate-pulse" />
            <div className="bg-white rounded-xl border border-stone-200 h-32 animate-pulse" />
          </div>
        )}

        {!isLoading && (
          <div className="space-y-6">
            {showEnvHint && originalSettings?.source === 'env_fallback' && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <i className="ri-information-line text-amber-500 text-sm"></i>
                  <span className="text-sm text-amber-700">
                    你正在使用环境变量中的默认配置。保存一次后，配置会迁移到本地文件，方便后续在 UI 内调整。
                  </span>
                </div>
                <button
                  onClick={() => setShowEnvHint(false)}
                  className="whitespace-nowrap text-xs text-amber-600 hover:text-amber-800 font-medium cursor-pointer transition-colors"
                >
                  我知道了
                </button>
              </div>
            )}

            <SettingsSection title="模型服务连接">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div className="md:col-span-2">
                  <TextInput
                    id="base_url"
                    label="服务地址"
                    value={form.base_url}
                    onChange={(v) => updateField('base_url', v)}
                    onBlur={() => validateField('base_url')}
                    error={errors.base_url}
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
                <div className="md:col-span-2">
                  <PasswordInput
                    id="api_key"
                    label="API 密钥"
                    value={form.api_key}
                    mask={originalSettings?.provider.api_key_masked ?? null}
                    onChange={(v) => updateField('api_key', v)}
                    error={null}
                    hint="密钥只保存在本地，不会上传到任何远端。"
                    placeholder="sk-..."
                    onClear={handleClearKey}
                  />
                </div>
                <TextInput
                  id="default_model"
                  label="默认模型"
                  value={form.default_model}
                  onChange={(v) => updateField('default_model', v)}
                  onBlur={() => validateField('default_model')}
                  error={errors.default_model}
                  placeholder="gpt-4o"
                />
                <NumberInput
                  id="timeout_seconds"
                  label="超时秒数"
                  value={form.timeout_seconds}
                  onChange={(v) => updateField('timeout_seconds', v)}
                  onBlur={() => validateField('timeout_seconds')}
                  error={errors.timeout_seconds}
                  min={5}
                  max={300}
                />
              </div>
            </SettingsSection>

            <SettingsSection title="各任务使用的模型" optional>
              <p className="text-sm text-stone-500 -mt-2 mb-1">
                留空表示使用上面的默认模型。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <TextInput
                  id="extract_model"
                  label="OCR 抽取"
                  value={form.extract_model}
                  onChange={(v) => updateField('extract_model', v)}
                  placeholder={form.default_model}
                />
                <TextInput
                  id="translate_model"
                  label="翻译"
                  value={form.translate_model}
                  onChange={(v) => updateField('translate_model', v)}
                  placeholder={form.default_model}
                />
                <TextInput
                  id="explain_model"
                  label="解释"
                  value={form.explain_model}
                  onChange={(v) => updateField('explain_model', v)}
                  placeholder={form.default_model}
                />
              </div>
            </SettingsSection>

            <SettingsSection title="高级">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.context_expansion_enabled}
                  onChange={(e) => updateField('context_expansion_enabled', e.target.checked)}
                  className="mt-0.5 w-4 h-4 rounded border-stone-300 text-amber-600 focus:ring-amber-500 cursor-pointer"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium text-stone-700">
                    跨页自动上下文
                  </div>
                  <p className="text-xs text-stone-400 mt-1">
                    选中内容提问时，自动附带选区前后几页的书内原文作为参考上下文，让 AI 理解跨页语境（需要该书已完成全书文本提取）。会小幅增加每次提问的 token 消耗。
                  </p>
                </div>
              </label>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.thinking_enabled}
                  onChange={(e) => updateField('thinking_enabled', e.target.checked)}
                  className="mt-0.5 w-4 h-4 rounded border-stone-300 text-amber-600 focus:ring-amber-500 cursor-pointer"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium text-stone-700">
                    启用 thinking 模式
                  </div>
                  <p className="text-xs text-stone-400 mt-1">
                    仅对 Qwen 兼容接口（含 dashscope/aliyuncs）生效；其他服务地址将自动忽略。开启后模型在回答前会先做内部思考，质量更稳但延迟与计费增加。
                  </p>
                </div>
              </label>
            </SettingsSection>

            <div className="space-y-4">
              {originalSettings && (
                <StatusIndicator
                  source={originalSettings.source}
                  providerReady={originalSettings.provider_ready}
                />
              )}

              {saveError && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                  <i className="ri-error-warning-line text-red-400 text-sm"></i>
                  <span className="text-sm text-red-600">{saveError}</span>
                </div>
              )}

              <div className="flex items-center justify-end gap-3">
                <button
                  onClick={handleCancel}
                  className="whitespace-nowrap px-5 py-2.5 text-sm font-medium text-stone-700 bg-white border border-stone-200 rounded-lg hover:bg-stone-50 cursor-pointer transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleSave}
                  disabled={isSaving || isSuccess}
                  className={`whitespace-nowrap flex items-center gap-2 px-5 py-2.5 text-sm font-medium rounded-lg cursor-pointer transition-colors ${
                    isSuccess
                      ? 'bg-emerald-600 text-white'
                      : 'bg-amber-600 text-white hover:bg-amber-700'
                  } disabled:opacity-60 disabled:cursor-not-allowed`}
                >
                  {isSaving && (
                    <>
                      <i className="ri-loader-4-line animate-spin text-sm"></i>
                      保存中...
                    </>
                  )}
                  {isSuccess && (
                    <>
                      <i className="ri-check-line text-sm"></i>
                      已保存
                    </>
                  )}
                  {!isSaving && !isSuccess && '保存'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {showLeaveConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/20" onClick={handleStay} />
          <div className="relative bg-white rounded-xl shadow-xl border border-stone-200 p-6 w-full max-w-sm mx-4">
            <h3 className="text-base font-semibold text-stone-700 mb-2">
              修改尚未保存
            </h3>
            <p className="text-sm text-stone-500 mb-5">
              确定要离开吗？未保存的改动将丢失。
            </p>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={handleStay}
                className="whitespace-nowrap px-4 py-2 text-sm font-medium text-stone-700 bg-white border border-stone-200 rounded-lg hover:bg-stone-50 cursor-pointer transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConfirmLeave}
                className="whitespace-nowrap px-4 py-2 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 cursor-pointer transition-colors"
              >
                放弃改动离开
              </button>
            </div>
          </div>
        </div>
      )}

      {toast && <Toast message={toast} />}
    </div>
  );
}

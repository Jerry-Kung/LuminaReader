import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { getSettings, saveSettings } from '@/services/api';
import type { Settings } from '@/services/api';
import {
  TextInput,
  NumberInput,
  PasswordInput,
  SettingsSection,
  StatusIndicator,
  Toast,
} from './components';

interface FormState {
  service_url: string;
  api_key: string;
  default_model: string;
  timeout_seconds: number;
  ocr_model: string;
  translate_model: string;
  explain_model: string;
}

interface FormErrors {
  service_url: string | null;
  default_model: string | null;
  timeout_seconds: string | null;
}

function isValidUrl(url: string): boolean {
  if (!url) return false;
  return url.startsWith('http://') || url.startsWith('https://');
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [originalSettings, setOriginalSettings] = useState<Settings | null>(null);
  const [form, setForm] = useState<FormState>({
    service_url: '',
    api_key: '',
    default_model: '',
    timeout_seconds: 60,
    ocr_model: '',
    translate_model: '',
    explain_model: '',
  });
  const [errors, setErrors] = useState<FormErrors>({
    service_url: null,
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
      const initialKey = data.api_key_mask || data.api_key || '';
      setForm({
        service_url: data.service_url,
        api_key: initialKey,
        default_model: data.default_model,
        timeout_seconds: data.timeout_seconds,
        ocr_model: data.ocr_model || '',
        translate_model: data.translate_model || '',
        explain_model: data.explain_model || '',
      });
      if (data.config_source === 'environment') {
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

  // Track changes
  useEffect(() => {
    if (!originalSettings) return;
    const keyChanged = form.api_key !== (originalSettings.api_key_mask || originalSettings.api_key || '');
    const otherChanged =
      form.service_url !== originalSettings.service_url ||
      form.default_model !== originalSettings.default_model ||
      form.timeout_seconds !== originalSettings.timeout_seconds ||
      form.ocr_model !== (originalSettings.ocr_model || '') ||
      form.translate_model !== (originalSettings.translate_model || '') ||
      form.explain_model !== (originalSettings.explain_model || '');
    setHasChanges(keyChanged || otherChanged);
  }, [form, originalSettings]);

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(message);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  const updateField = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (key === 'service_url') {
      setErrors((prev) => ({ ...prev, service_url: null }));
    }
    if (key === 'default_model') {
      setErrors((prev) => ({ ...prev, default_model: null }));
    }
    if (key === 'timeout_seconds') {
      setErrors((prev) => ({ ...prev, timeout_seconds: null }));
    }
  }, []);

  const validateField = useCallback((key: keyof FormState) => {
    if (key === 'service_url') {
      if (!isValidUrl(form.service_url)) {
        setErrors((prev) => ({ ...prev, service_url: '请输入合法的 http(s) 地址' }));
      } else {
        setErrors((prev) => ({ ...prev, service_url: null }));
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
      service_url: !isValidUrl(form.service_url) ? '请输入合法的 http(s) 地址' : null,
      default_model: !form.default_model.trim() ? '默认模型不能为空' : null,
      timeout_seconds: form.timeout_seconds < 5 || form.timeout_seconds > 300 ? '超时秒数应在 5 到 300 之间' : null,
    };
    setErrors(newErrors);

    if (newErrors.service_url || newErrors.default_model || newErrors.timeout_seconds) {
      return;
    }

    setSaveState('saving');
    setSaveError(null);

    try {
      const result = await saveSettings({
        service_url: form.service_url,
        api_key: form.api_key,
        default_model: form.default_model,
        timeout_seconds: form.timeout_seconds,
        ocr_model: form.ocr_model,
        translate_model: form.translate_model,
        explain_model: form.explain_model,
      });

      if (result.success) {
        setSaveState('success');
        showToast('Settings saved');
        setHasChanges(false);
        await loadSettings();
        setTimeout(() => {
          setSaveState('idle');
        }, 2000);
      } else {
        setSaveState('error');
        setSaveError(result.error || '保存失败，请检查后端日志');
      }
    } catch (err: any) {
      setSaveState('error');
      setSaveError(err.message || '无法写入配置文件，请检查应用数据目录的写权限');
    }
  }, [form, showToast, loadSettings]);

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

  // Prevent browser back if unsaved
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
            {/* Environment hint */}
            {showEnvHint && originalSettings?.config_source === 'environment' && (
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

            {/* Section 1: Model Connection */}
            <SettingsSection title="模型服务连接">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div className="md:col-span-2">
                  <TextInput
                    id="service_url"
                    label="服务地址"
                    value={form.service_url}
                    onChange={(v) => updateField('service_url', v)}
                    onBlur={() => validateField('service_url')}
                    error={errors.service_url}
                    placeholder="https://api.openai.com/v1"
                  />
                </div>
                <div className="md:col-span-2">
                  <PasswordInput
                    id="api_key"
                    label="API 密钥"
                    value={form.api_key}
                    mask={originalSettings?.api_key_mask || null}
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

            {/* Section 2: Task Models (Optional) */}
            <SettingsSection title="各任务使用的模型" optional>
              <p className="text-sm text-stone-500 -mt-2 mb-1">
                留空表示使用上面的默认模型。
              </p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <TextInput
                  id="ocr_model"
                  label="OCR 抽取"
                  value={form.ocr_model}
                  onChange={(v) => updateField('ocr_model', v)}
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

            {/* Section 3: Status + Actions */}
            <div className="space-y-4">
              {originalSettings && (
                <StatusIndicator
                  configSource={originalSettings.config_source}
                  isReady={originalSettings.is_ready}
                />
              )}

              {/* Save error bar */}
              {saveError && (
                <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                  <i className="ri-error-warning-line text-red-400 text-sm"></i>
                  <span className="text-sm text-red-600">{saveError}</span>
                </div>
              )}

              {/* Action buttons */}
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

      {/* Leave confirmation dialog */}
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

      {/* Toast */}
      {toast && <Toast message={toast} />}
    </div>
  );
}
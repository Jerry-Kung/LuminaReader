export interface Settings {
  service_url: string;
  api_key: string;
  api_key_mask: string | null;
  default_model: string;
  timeout_seconds: number;
  ocr_model: string;
  translate_model: string;
  explain_model: string;
  config_source: 'environment' | 'local';
  is_ready: boolean;
}

export interface SettingsForm {
  service_url: string;
  api_key: string;
  default_model: string;
  timeout_seconds: number;
  ocr_model: string;
  translate_model: string;
  explain_model: string;
}

let currentSettings: Settings = {
  service_url: 'https://api.openai.com/v1',
  api_key: 'sk-proj-xxx-very-long-key-end-abcd',
  api_key_mask: 'sk-***...abcd',
  default_model: 'gpt-4o',
  timeout_seconds: 60,
  ocr_model: '',
  translate_model: '',
  explain_model: '',
  config_source: 'environment',
  is_ready: true,
};

export function fetchSettings(): Promise<Settings> {
  return new Promise((resolve) => {
    setTimeout(() => resolve({ ...currentSettings }), 300);
  });
}

export function saveSettingsToMock(form: SettingsForm): Promise<{ success: boolean; error?: string }> {
  return new Promise((resolve) => {
    setTimeout(() => {
      // Validate URL
      if (!form.service_url.startsWith('http://') && !form.service_url.startsWith('https://')) {
        resolve({ success: false, error: '请输入合法的 http(s) 地址' });
        return;
      }
      // Validate timeout
      if (form.timeout_seconds < 5 || form.timeout_seconds > 300) {
        resolve({ success: false, error: '超时秒数应在 5 到 300 之间' });
        return;
      }
      // Validate default model
      if (!form.default_model.trim()) {
        resolve({ success: false, error: '默认模型不能为空' });
        return;
      }

      // Update current settings
      currentSettings = {
        ...currentSettings,
        service_url: form.service_url,
        api_key: form.api_key,
        api_key_mask: form.api_key ? `sk-***...${form.api_key.slice(-4)}` : null,
        default_model: form.default_model,
        timeout_seconds: form.timeout_seconds,
        ocr_model: form.ocr_model,
        translate_model: form.translate_model,
        explain_model: form.explain_model,
        config_source: 'local',
        is_ready: !!form.api_key,
      };

      resolve({ success: true });
    }, 600);
  });
}
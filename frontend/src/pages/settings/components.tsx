import { useState, useRef } from 'react';

interface TextInputProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string | null;
  hint?: string;
  placeholder?: string;
  type?: 'text' | 'password';
  disabled?: boolean;
  rightElement?: React.ReactNode;
}

export function TextInput({
  id,
  label,
  value,
  onChange,
  onBlur,
  error,
  hint,
  placeholder,
  type = 'text',
  disabled,
  rightElement,
}: TextInputProps) {
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => {
            setIsFocused(false);
            onBlur?.();
          }}
          placeholder={placeholder}
          disabled={disabled}
          className={`w-full text-sm text-stone-700 bg-white border rounded-md px-3 py-2.5 transition-colors focus:outline-none disabled:bg-stone-50 disabled:text-stone-400 ${
            error ? 'border-red-300 focus:border-red-400' : 'border-stone-200 focus:border-amber-400'
          } ${rightElement ? 'pr-10' : ''}`}
        />
        {rightElement && (
          <div className="absolute right-2 top-1/2 -translate-y-1/2">
            {rightElement}
          </div>
        )}
      </div>
      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
      {!error && hint && (
        <p className="text-xs text-stone-400">{hint}</p>
      )}
    </div>
  );
}

interface NumberInputProps {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
  onBlur?: () => void;
  error?: string | null;
  min?: number;
  max?: number;
}

export function NumberInput({
  id,
  label,
  value,
  onChange,
  onBlur,
  error,
  min,
  max,
}: NumberInputProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      <input
        id={id}
        type="number"
        value={value}
        onChange={(e) => {
          const v = e.target.value === '' ? 0 : parseInt(e.target.value, 10);
          onChange(v);
        }}
        onBlur={onBlur}
        min={min}
        max={max}
        className={`w-full text-sm text-stone-700 bg-white border rounded-md px-3 py-2.5 transition-colors focus:outline-none ${
          error ? 'border-red-300 focus:border-red-400' : 'border-stone-200 focus:border-amber-400'
        }`}
      />
      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
    </div>
  );
}

interface PasswordInputProps {
  id: string;
  label: string;
  value: string;
  mask: string | null;
  onChange: (value: string) => void;
  onBlur?: () => void;
  error?: string | null;
  hint?: string;
  placeholder?: string;
  onClear?: () => void;
}

export function PasswordInput({
  id,
  label,
  value,
  mask,
  onChange,
  onBlur,
  error,
  hint,
  placeholder,
  onClear,
}: PasswordInputProps) {
  const [show, setShow] = useState(false);
  const [hasFocus, setHasFocus] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // When masked and user clicks/focuses, clear the mask
  const handleFocus = () => {
    setHasFocus(true);
    if (mask && value === mask) {
      onChange('');
    }
  };

  const handleBlur = () => {
    setHasFocus(false);
    onBlur?.();
  };

  // Display value: if masked and not focused, show mask; otherwise show actual value
  const displayValue = mask && !hasFocus && value === mask ? mask : value;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          type={show ? 'text' : 'password'}
          value={displayValue}
          onChange={(e) => onChange(e.target.value)}
          onFocus={handleFocus}
          onBlur={handleBlur}
          placeholder={placeholder}
          className={`w-full text-sm text-stone-700 bg-white border rounded-md px-3 py-2.5 pr-20 transition-colors focus:outline-none ${
            error ? 'border-red-300 focus:border-red-400' : 'border-stone-200 focus:border-amber-400'
          }`}
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          <button
            type="button"
            onClick={() => setShow(!show)}
            className="w-7 h-7 flex items-center justify-center rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 transition-colors cursor-pointer"
            title={show ? 'Hide key' : 'Show key'}
          >
            <i className={`${show ? 'ri-eye-off-line' : 'ri-eye-line'} text-xs`}></i>
          </button>
          {onClear && (
            <button
              type="button"
              onClick={onClear}
              className="w-7 h-7 flex items-center justify-center rounded text-stone-400 hover:text-red-500 hover:bg-red-50 transition-colors cursor-pointer"
              title="Clear key"
            >
              <i className="ri-close-line text-xs"></i>
            </button>
          )}
        </div>
      </div>
      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
      {!error && hint && (
        <p className="text-xs text-stone-400">{hint}</p>
      )}
    </div>
  );
}

interface SettingsSectionProps {
  title: string;
  children: React.ReactNode;
  optional?: boolean;
}

export function SettingsSection({ title, children, optional }: SettingsSectionProps) {
  return (
    <div className="bg-white rounded-xl border border-stone-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-stone-100">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-stone-700">{title}</h2>
          {optional && (
            <span className="text-[10px] font-medium text-stone-400 bg-stone-100 px-1.5 py-0.5 rounded">
              Optional
            </span>
          )}
        </div>
      </div>
      <div className="px-5 py-5 space-y-5">
        {children}
      </div>
    </div>
  );
}

interface StatusIndicatorProps {
  configSource: 'environment' | 'local';
  isReady: boolean;
}

export function StatusIndicator({ configSource, isReady }: StatusIndicatorProps) {
  return (
    <div className="bg-white rounded-xl border border-stone-200 overflow-hidden">
      <div className="px-5 py-4 border-b border-stone-100">
        <h2 className="text-sm font-semibold text-stone-700">Current Status</h2>
      </div>
      <div className="px-5 py-5">
        <div className="flex items-center justify-between">
          {/* Config source */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-stone-500">Config source</span>
            <span
              className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full ${
                configSource === 'local'
                  ? 'bg-amber-50 text-amber-700 border border-amber-200'
                  : 'bg-stone-100 text-stone-500 border border-stone-200'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  configSource === 'local' ? 'bg-amber-500' : 'bg-stone-400'
                }`}
              />
              {configSource === 'local' ? '应用内' : '环境变量'}
            </span>
          </div>

          {/* Readiness */}
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              {isReady && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span
                className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                  isReady ? 'bg-emerald-500' : 'bg-stone-300'
                }`}
              />
            </span>
            <span className={`text-sm font-medium ${isReady ? 'text-emerald-600' : 'text-stone-400'}`}>
              {isReady ? '已就绪' : '未配置密钥'}
            </span>
          </div>
        </div>
        <p className="text-xs text-stone-400 mt-4">
          修改后立即生效，无需重启应用。
        </p>
      </div>
    </div>
  );
}

interface ToastProps {
  message: string;
  type?: 'success' | 'error';
  onClose?: () => void;
}

export function Toast({ message, type = 'success', onClose }: ToastProps) {
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-[fadeInUp_0.2s_ease-out]">
      <div className={`flex items-center gap-2 text-sm px-4 py-2.5 rounded-lg shadow-lg ${
        type === 'success'
          ? 'bg-stone-800 text-white'
          : 'bg-red-700 text-white'
      }`}>
        <i className={`${type === 'success' ? 'ri-check-line text-amber-400' : 'ri-error-warning-line text-red-200'} text-sm`}></i>
        {message}
        {onClose && (
          <button
            onClick={onClose}
            className="ml-2 w-5 h-5 flex items-center justify-center rounded text-white/60 hover:text-white cursor-pointer"
          >
            <i className="ri-close-line text-xs"></i>
          </button>
        )}
      </div>
    </div>
  );
}
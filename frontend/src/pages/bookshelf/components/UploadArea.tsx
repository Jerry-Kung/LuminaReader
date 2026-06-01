import { useState, useRef, useCallback, useEffect } from 'react';
import type { UploadProgress } from '@/services/api';

interface UploadAreaProps {
  isUploading: boolean;
  uploadProgress: UploadProgress | null;
  onFileSelect: (file: File) => void;
  onUploadCancel: () => void;
}

export default function UploadArea({ isUploading, uploadProgress, onFileSelect, onUploadCancel }: UploadAreaProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [dragError, setDragError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (dragTimeoutRef.current) clearTimeout(dragTimeoutRef.current);
    setIsDragging(true);
    setDragError(null);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragTimeoutRef.current = setTimeout(() => setIsDragging(false), 50);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    setDragError(null);

    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;

    const file = files[0];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setDragError('只支持 PDF 文件');
      return;
    }
    onFileSelect(file);
  }, [onFileSelect]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFileSelect(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [onFileSelect]);

  useEffect(() => {
    return () => {
      if (dragTimeoutRef.current) clearTimeout(dragTimeoutRef.current);
    };
  }, []);

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className={`w-full rounded-xl border-2 border-dashed transition-all duration-200 ${
        isDragging
          ? 'border-amber-400 bg-amber-50/50'
          : 'border-stone-200 bg-white hover:border-stone-300'
      }`}
    >
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-4">
          <div className={`w-10 h-10 flex items-center justify-center rounded-lg ${isDragging ? 'bg-amber-100' : 'bg-stone-100'}`}>
            <i className={`ri-upload-cloud-2-line text-lg ${isDragging ? 'text-amber-600' : 'text-stone-500'}`}></i>
          </div>
          <div>
            <p className="text-sm font-medium text-stone-700">
              {isUploading ? '上传中…' : '上传一本书'}
            </p>
            <p className="text-xs text-stone-400 mt-0.5">
              {isUploading
                ? `${uploadProgress?.percentage || 0}% 完成`
                : '拖一份 PDF 到这里，或点击选择文件'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {isUploading && uploadProgress ? (
            <>
              <div className="w-32 h-1.5 bg-stone-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-amber-500 rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress.percentage}%` }}
                />
              </div>
              <span className="text-xs text-stone-500 w-9 text-right">{uploadProgress.percentage}%</span>
              <button
                onClick={onUploadCancel}
                className="w-7 h-7 flex items-center justify-center rounded-md text-stone-400 hover:text-red-500 hover:bg-red-50 cursor-pointer transition-colors"
              >
                <i className="ri-close-line text-sm"></i>
              </button>
            </>
          ) : (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileInput}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                className="whitespace-nowrap flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-700 bg-stone-100 rounded-lg hover:bg-stone-200 cursor-pointer transition-colors"
              >
                <i className="ri-folder-open-line text-sm"></i>
                选择文件
              </button>
            </>
          )}
        </div>
      </div>

      {/* Drag error */}
      {dragError && (
        <div className="px-5 pb-3">
          <div className="flex items-center gap-2 text-xs text-red-500 bg-red-50 rounded-md px-3 py-2">
            <i className="ri-error-warning-line"></i>
            {dragError}
          </div>
        </div>
      )}
    </div>
  );
}
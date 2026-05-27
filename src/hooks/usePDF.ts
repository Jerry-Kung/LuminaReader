import { useState, useRef, useCallback, useEffect } from 'react';
import * as pdfjsLib from 'pdfjs-dist';

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface UsePDFReturn {
  pdfDoc: pdfjsLib.PDFDocumentProxy | null;
  numPages: number;
  currentPage: number;
  scale: number;
  isLoading: boolean;
  error: string | null;
  fileName: string;
  loadPDF: (file: File) => void;
  goToPage: (page: number) => void;
  nextPage: () => void;
  prevPage: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  setScale: (scale: number) => void;
}

export function usePDF(): UsePDFReturn {
  const [pdfDoc, setPdfDoc] = useState<pdfjsLib.PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1.2);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState('');
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);

  const loadPDF = useCallback((file: File) => {
    setIsLoading(true);
    setError(null);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const typedArray = new Uint8Array(e.target!.result as ArrayBuffer);
        const doc = await pdfjsLib.getDocument({ data: typedArray }).promise;
        pdfDocRef.current = doc;
        setPdfDoc(doc);
        setNumPages(doc.numPages);
        setCurrentPage(1);
        setScale(1.2);
      } catch (err) {
        setError('Failed to load PDF. Please make sure it\'s a valid PDF file.');
        console.error('PDF load error:', err);
      } finally {
        setIsLoading(false);
      }
    };
    reader.onerror = () => {
      setError('Failed to read the file.');
      setIsLoading(false);
    };
    reader.readAsArrayBuffer(file);
  }, []);

  const goToPage = useCallback((page: number) => {
    if (page >= 1 && page <= numPages) {
      setCurrentPage(page);
    }
  }, [numPages]);

  const nextPage = useCallback(() => {
    if (currentPage < numPages) {
      setCurrentPage((p) => p + 1);
    }
  }, [currentPage, numPages]);

  const prevPage = useCallback(() => {
    if (currentPage > 1) {
      setCurrentPage((p) => p - 1);
    }
  }, [currentPage]);

  const zoomIn = useCallback(() => {
    setScale((s) => Math.min(s + 0.2, 3.0));
  }, []);

  const zoomOut = useCallback(() => {
    setScale((s) => Math.max(s - 0.2, 0.4));
  }, []);

  useEffect(() => {
    return () => {
      if (pdfDocRef.current) {
        pdfDocRef.current.destroy();
        pdfDocRef.current = null;
      }
    };
  }, []);

  return {
    pdfDoc,
    numPages,
    currentPage,
    scale,
    isLoading,
    error,
    fileName,
    loadPDF,
    goToPage,
    nextPage,
    prevPage,
    zoomIn,
    zoomOut,
    setScale,
  };
}
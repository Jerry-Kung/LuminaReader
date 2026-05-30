interface EmptyStateProps {
  onUploadClick: () => void;
}

export default function EmptyState({ onUploadClick }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-20 h-20 flex items-center justify-center rounded-2xl bg-stone-100 mb-5">
        <i className="ri-book-shelf-line text-3xl text-stone-300"></i>
      </div>
      <h2 className="text-lg font-medium text-stone-600 mb-2">
        Your bookshelf is empty
      </h2>
      <p className="text-sm text-stone-400 mb-6 max-w-xs">
        Upload your first PDF to start reading and asking questions
      </p>
      <button
        onClick={onUploadClick}
        className="whitespace-nowrap flex items-center gap-2 px-6 py-3 text-sm font-medium text-white bg-amber-600 rounded-lg hover:bg-amber-700 cursor-pointer transition-colors shadow-sm"
      >
        <i className="ri-upload-cloud-line text-sm"></i>
        Upload your first book
      </button>
      <p className="text-xs text-stone-300 mt-4">
        You can also drag a PDF anywhere on this page
      </p>
    </div>
  );
}
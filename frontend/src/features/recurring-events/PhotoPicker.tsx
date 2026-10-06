import { useEffect, useRef, useState } from "react";

export const PHOTO_ACCEPT = "image/*,.heic,.heif";

interface PhotoPickerProps {
  selectedFile: File | null;
  onSelect: (file: File | null) => void;
}

/**
 * Shared photo picker for recurring-event records: file dialog plus single
 * file drag & drop. Dropping multiple files keeps the current selection and
 * shows an inline error. Final format validation stays server-side.
 */
export function PhotoPicker({ selectedFile, onSelect }: PhotoPickerProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);

  // The parent clears selectedFile after submit; reset the input so the same
  // file can be picked again.
  useEffect(() => {
    if (selectedFile === null && inputRef.current) {
      inputRef.current.value = "";
    }
  }, [selectedFile]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const files = e.dataTransfer.files;
    if (files.length === 1 && files[0]) {
      setDropError(null);
      onSelect(files[0]);
    } else if (files.length > 1) {
      setDropError("写真は1枚までです。1つのファイルだけをドロップしてください。");
    } else {
      setDropError("画像ファイルを受け取れませんでした。ファイルを選択してください。");
    }
  };

  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault();
        if (!e.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={(e) => {
        e.preventDefault();
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragging(false);
      }}
      onDrop={handleDrop}
      data-dragging={dragging ? "true" : "false"}
      className={`rounded-lg border border-dashed px-3 py-2 transition-colors ${
        dragging ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-white"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={PHOTO_ACCEPT}
        onChange={(e) => {
          setDropError(null);
          onSelect(e.target.files?.[0] || null);
        }}
        className="block w-full text-xs text-slate-500 file:mr-2 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:font-semibold file:bg-slate-100 file:text-slate-700 hover:file:bg-slate-200"
      />
      <p className="mt-1 text-[11px] text-slate-400">
        ファイルを選択するか、画像を1枚ドラッグ＆ドロップ
      </p>
      {selectedFile && (
        <div className="mt-1 flex items-center gap-2 text-xs">
          <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
            選択中: {selectedFile.name}
          </span>
          <button
            type="button"
            onClick={() => onSelect(null)}
            className="shrink-0 text-xs text-slate-500 hover:underline"
          >
            取り消す
          </button>
        </div>
      )}
      {dropError && (
        <p role="alert" className="mt-1 text-xs text-red-600">
          {dropError}
        </p>
      )}
    </div>
  );
}

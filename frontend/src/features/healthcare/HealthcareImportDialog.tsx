import { useCallback, useEffect, useRef, useState } from "react";
import { getApiErrorMessage } from "../../utils/error";
import { importHealthcareZip } from "../../api/client";
import type { HealthcareImportResponse } from "../../api/types";

export interface HealthcareImportDialogProps {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}

type SourceMode = "file" | "path";

export default function HealthcareImportDialog({
  open,
  onClose,
  onImported,
}: HealthcareImportDialogProps) {
  const [mode, setMode] = useState<SourceMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [path, setPath] = useState("");
  const [dragging, setDragging] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<HealthcareImportResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => {
    setMode("file");
    setFile(null);
    setPath("");
    setDragging(false);
    setImporting(false);
    setError(null);
    setResult(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const close = useCallback(() => {
    if (importing) return;
    reset();
    onClose();
  }, [importing, onClose, reset]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  if (!open) return null;

  const canImport = mode === "file" ? file !== null : path.trim() !== "";

  const selectMode = (next: SourceMode) => {
    if (importing) return;
    setMode(next);
    setResult(null);
    setError(null);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (importing) return;
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setMode("file");
      setFile(dropped);
      setResult(null);
      setError(null);
    }
  };

  const handleImport = async () => {
    if (!canImport || importing) return;
    setImporting(true);
    setError(null);
    setResult(null);
    try {
      const res = await importHealthcareZip(
        mode === "file" && file ? { file } : { path: path.trim() },
      );
      setResult(res);
      onImported();
    } catch (e) {
      setError(getApiErrorMessage(e, "ヘルスケアデータの取込に失敗しました"));
    } finally {
      setImporting(false);
    }
  };

  const newCount = result
    ? result.stats.records_inserted +
      result.stats.workouts_inserted +
      result.stats.activity_summaries_inserted
    : 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="ヘルスケアデータのインポート"
      data-testid="healthcare-import-dialog"
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
    >
      <div className="flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-100 bg-slate-50 p-4">
          <h3 className="text-sm font-bold text-slate-900">ヘルスケアデータのインポート</h3>
          <button
            onClick={close}
            disabled={importing}
            className="text-xs text-slate-400 transition-colors hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto p-5 text-xs text-slate-700">
          <p className="text-slate-500">
            Apple Health から書き出した <code className="rounded bg-slate-100 px-1 py-0.5">export.zip</code> を取り込みます。既に取り込み済みの記録は重複として除外され、新しい記録だけが追加されます。
          </p>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => selectMode("file")}
              disabled={importing}
              className={`rounded px-3 py-1.5 text-xs font-semibold ${
                mode === "file"
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              } cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`}
            >
              zip をアップロード
            </button>
            <button
              type="button"
              onClick={() => selectMode("path")}
              disabled={importing}
              className={`rounded px-3 py-1.5 text-xs font-semibold ${
                mode === "path"
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              } cursor-pointer disabled:cursor-not-allowed disabled:opacity-50`}
            >
              サーバー上のパスを指定
            </button>
          </div>

          {mode === "file" ? (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                if (!importing) setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.stopPropagation();
                handleDrop(e);
              }}
              onClick={() => {
                if (!importing) fileInputRef.current?.click();
              }}
              data-testid="healthcare-import-dropzone"
              className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
                importing
                  ? "cursor-not-allowed opacity-50"
                  : dragging
                    ? "border-blue-500 bg-blue-50"
                    : "border-slate-300 bg-slate-50 hover:bg-slate-100"
              }`}
            >
              <p className="text-sm font-semibold text-slate-700">
                {file ? file.name : "ここに export.zip をドラッグ＆ドロップ"}
              </p>
              <p className="text-[11px] text-slate-500">
                {file
                  ? `${(file.size / (1024 * 1024)).toFixed(1)} MB`
                  : "またはクリックしてファイルを選択"}
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip,application/zip"
                disabled={importing}
                className="hidden"
                data-testid="healthcare-import-file-input"
                onChange={(e) => {
                  const selected = e.target.files?.[0] ?? null;
                  setFile(selected);
                  setResult(null);
                  setError(null);
                }}
              />
            </div>
          ) : (
            <div>
              <label className="mb-1 block text-[11px] font-bold text-slate-700">
                Mac 上の zip パス
              </label>
              <input
                type="text"
                value={path}
                disabled={importing}
                onChange={(e) => {
                  setPath(e.target.value);
                  setResult(null);
                  setError(null);
                }}
                placeholder="~/Downloads/export.zip"
                data-testid="healthcare-import-path-input"
                className="w-full rounded border border-slate-300 px-2.5 py-1.5 text-xs focus:border-slate-900 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                巨大な zip はアップロードせず、この方法で直接取り込めます。
              </p>
            </div>
          )}

          {importing && (
            <p className="text-sm text-slate-500" data-testid="healthcare-import-progress">
              取り込み中です…（完了まで数分かかることがあります）
            </p>
          )}
          {error && (
            <p className="text-sm text-red-600" data-testid="healthcare-import-error">
              {error}
            </p>
          )}

          {result && (
            <div
              className="rounded-lg border border-emerald-200 bg-emerald-50 p-3"
              data-testid="healthcare-import-result"
            >
              <p className="text-sm font-semibold text-emerald-800">取り込みが完了しました</p>
              <ul className="mt-1 space-y-0.5 text-[11px] text-emerald-700">
                <li>新規: {newCount.toLocaleString()} 件</li>
                <li>重複として除外: {result.stats.ignored_duplicates.toLocaleString()} 件</li>
                <li>ECG ファイル: {result.stats.ecg_files.toLocaleString()} 件</li>
              </ul>
            </div>
          )}
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-slate-100 bg-slate-50 p-3">
          <button
            type="button"
            onClick={close}
            disabled={importing}
            className="rounded bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {result ? "閉じる" : "キャンセル"}
          </button>
          <button
            type="button"
            onClick={handleImport}
            disabled={!canImport || importing}
            data-testid="healthcare-import-submit"
            className="rounded bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {importing ? "取り込み中…" : "インポート"}
          </button>
        </div>
      </div>
    </div>
  );
}

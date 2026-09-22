import { useEffect, useState } from "react";
import { listVaultFiles } from "../../api/client";
import type { VaultFileListItem } from "../../api/types";

export interface VaultPathFieldProps {
  value: string;
  onChange: (path: string) => void;
  testIdPrefix: string;
}

/**
 * Single-select Vault path field: free text plus a searchable picker.
 *
 * The picker reuses the ``listVaultFiles`` API but is intentionally separate
 * from the Agent context-ref picker (multi-select, chat-bound).
 */
export default function VaultPathField({
  value,
  onChange,
  testIdPrefix,
}: VaultPathFieldProps) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState<VaultFileListItem[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || files !== null) return;
    let alive = true;
    setError(null);
    listVaultFiles()
      .then((response) => {
        if (alive) setFiles(response.items);
      })
      .catch((err: unknown) => {
        if (alive) {
          setError(
            err instanceof Error ? err.message : "ファイル一覧の取得に失敗しました",
          );
        }
      });
    return () => {
      alive = false;
    };
  }, [open, files]);

  const needle = query.trim().toLowerCase();
  const filtered = (files ?? []).filter(
    (file) => !needle || file.relative_path.toLowerCase().includes(needle),
  );

  return (
    <div className="space-y-1">
      <div className="flex gap-1">
        <input
          data-testid={`${testIdPrefix}-vault-path`}
          className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
          value={value}
          placeholder="notes/daily.md"
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          data-testid={`${testIdPrefix}-vault-open`}
          className="cursor-pointer whitespace-nowrap rounded border border-slate-300 px-2 text-[11px] text-slate-600"
          onClick={() => setOpen(true)}
        >
          選択
        </button>
      </div>

      {open && (
        <div
          data-testid={`${testIdPrefix}-vault-modal`}
          className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="flex max-h-[70vh] w-96 flex-col overflow-hidden rounded bg-white shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="border-b border-slate-100 p-2">
              <input
                autoFocus
                data-testid={`${testIdPrefix}-vault-search`}
                className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
                placeholder="ファイルを検索"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-auto py-1">
              {error && (
                <p className="px-3 py-2 text-xs text-rose-700">{error}</p>
              )}
              {!error && files === null && (
                <p className="px-3 py-2 text-xs text-slate-500">読込中…</p>
              )}
              {filtered.map((file) => (
                <button
                  key={file.relative_path}
                  type="button"
                  className="block w-full truncate px-3 py-1.5 text-left font-mono text-xs hover:bg-slate-50"
                  onClick={() => {
                    onChange(file.relative_path);
                    setOpen(false);
                    setQuery("");
                  }}
                >
                  {file.relative_path}
                </button>
              ))}
              {files !== null && filtered.length === 0 && (
                <p className="px-3 py-2 text-xs text-slate-500">該当なし</p>
              )}
            </div>
            <div className="border-t border-slate-100 p-2 text-right">
              <button
                type="button"
                className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-xs text-white"
                onClick={() => setOpen(false)}
              >
                閉じる
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

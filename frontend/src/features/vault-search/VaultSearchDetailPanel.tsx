import type { VaultSearchHit } from "../../api/types";
import { formatScore, formatMtime, buildObsidianUrl } from "./utils";

export interface VaultSearchDetailPanelProps {
  hit: VaultSearchHit;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function VaultSearchDetailPanel({ hit, notify }: VaultSearchDetailPanelProps) {
  const meta = hit.metadata;

  const handleOpenInObsidian = () => {
    const url = buildObsidianUrl(hit);
    if (!url) {
      notify("Obsidian の vault 名が不明です", "error");
      return;
    }
    window.open(url, "_blank");
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-4 space-y-2">
        <h2 className="text-base font-semibold text-slate-900">詳細</h2>
        <table className="w-full text-xs text-slate-600">
          <tbody>
            <tr>
              <td className="pr-3 font-medium">Score</td>
              <td className="font-mono">{formatScore(hit.score)}</td>
            </tr>
            {meta.relative_path && (
              <tr>
                <td className="pr-3 font-medium">Path</td>
                <td>{meta.relative_path}</td>
              </tr>
            )}
            {meta.file_path && (
              <tr>
                <td className="pr-3 font-medium">Full Path</td>
                <td>{meta.file_path}</td>
              </tr>
            )}
            {meta.chunk_index !== undefined && meta.chunk_index !== null && (
              <tr>
                <td className="pr-3 font-medium">Chunk</td>
                <td>{meta.chunk_index}</td>
              </tr>
            )}
            {meta.mtime !== undefined && meta.mtime !== null && (
              <tr>
                <td className="pr-3 font-medium">Modified</td>
                <td>{formatMtime(meta.mtime)}</td>
              </tr>
            )}
            {meta.vault_name && (
              <tr>
                <td className="pr-3 font-medium">Vault</td>
                <td>{meta.vault_name}</td>
              </tr>
            )}
          </tbody>
        </table>
        <button
          type="button"
          onClick={handleOpenInObsidian}
          className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-700"
        >
          Obsidian で開く
        </button>
      </div>
      <div className="flex-1">
        <h3 className="mb-1 text-xs font-medium text-slate-500">本文</h3>
        <pre className="whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">
          {hit.content}
        </pre>
      </div>
    </div>
  );
}

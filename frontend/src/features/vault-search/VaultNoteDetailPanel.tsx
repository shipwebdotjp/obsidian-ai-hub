import { useEffect, useState } from "react";
import { getVaultFile } from "../../api/client";
import MarkdownPreview from "../../components/MarkdownPreview";
import { buildObsidianUrl, parseNoteContent } from "../../utils/vault";
import { formatMtime, formatScore } from "./utils";

export interface VaultNoteDetailPanelProps {
  relativePath: string;
  notify: (msg: string, kind?: "info" | "error") => void;
  score?: number;
  chunkIndex?: number | null;
  mtime?: number | null;
}

/**
 * 検索結果とファイルエクスプローラーで共用するノートビューアー。
 * 本文・frontmatter・Markdown 描画・取得エラー・Obsidian 起動を一箇所に集約する。
 */
export default function VaultNoteDetailPanel({
  relativePath,
  notify,
  score,
  chunkIndex,
  mtime,
}: VaultNoteDetailPanelProps) {
  const [content, setContent] = useState<string>("");
  const [vaultName, setVaultName] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!relativePath) {
      setContent("");
      setVaultName(null);
      setError("相対パスが不足しているため、ノートの全文を取得できません");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setContent("");
    setVaultName(null);

    getVaultFile(relativePath, controller.signal)
      .then((res) => {
        setContent(res.content);
        setVaultName(res.vault_name ?? null);
        setError(null);
      })
      .catch((err) => {
        if ((err instanceof DOMException && err.name === "AbortError") || controller.signal.aborted) {
          return;
        }
        setError(err instanceof Error && err.message ? err.message : "ノートの取得に失敗しました");
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [relativePath]);

  const handleOpenInObsidian = () => {
    const url = buildObsidianUrl(vaultName, relativePath);
    if (!url) {
      notify("Obsidian の vault 名が不明です", "error");
      return;
    }
    window.open(url, "_blank");
  };

  const { frontmatter, body } = parseNoteContent(content);

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-4 space-y-2">
        <h2 className="text-base font-semibold text-slate-900">詳細</h2>
        <table className="w-full text-xs text-slate-600">
          <tbody>
            {score !== undefined && (
              <tr>
                <td className="pr-3 font-medium w-20">Score</td>
                <td className="font-mono">{formatScore(score)}</td>
              </tr>
            )}
            {relativePath && (
              <tr>
                <td className="pr-3 font-medium">Path</td>
                <td>{relativePath}</td>
              </tr>
            )}
            {chunkIndex !== undefined && chunkIndex !== null && (
              <tr>
                <td className="pr-3 font-medium">Chunk</td>
                <td>{chunkIndex}</td>
              </tr>
            )}
            {mtime !== undefined && mtime !== null && (
              <tr>
                <td className="pr-3 font-medium">Modified</td>
                <td>{formatMtime(mtime)}</td>
              </tr>
            )}
            {vaultName && (
              <tr>
                <td className="pr-3 font-medium">Vault</td>
                <td>{vaultName}</td>
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
      <div className="flex-1 flex flex-col min-h-0 mt-4">
        <h3 className="mb-2 text-xs font-medium text-slate-500">本文</h3>
        {loading && (
          <div className="p-4 rounded border border-slate-200 bg-slate-50 text-sm text-slate-500 animate-pulse">
            読み込み中…
          </div>
        )}
        {error && (
          <div className="p-4 rounded border border-red-200 bg-red-50 text-sm text-red-600">
            {error}
          </div>
        )}
        {!loading && !error && (
          <div className="flex-1 text-sm leading-relaxed text-slate-800">
            {frontmatter && (
              <pre className="mb-4 whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-3 text-xs font-mono text-slate-700">
                {frontmatter}
              </pre>
            )}
            <MarkdownPreview content={body} />
          </div>
        )}
      </div>
    </div>
  );
}

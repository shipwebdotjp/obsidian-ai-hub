import { useEffect, useState } from "react";
import type { VaultSearchHit } from "../../api/types";
import { formatScore, formatMtime, buildObsidianUrl } from "./utils";
import { getVaultFile } from "../../api/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export interface VaultSearchDetailPanelProps {
  hit: VaultSearchHit;
  notify: (msg: string, kind?: "info" | "error") => void;
}

function parseNoteContent(rawContent: string): { frontmatter: string | null; body: string } {
  const lines = rawContent.split(/\r?\n/);
  if (lines.length > 0 && lines[0] === "---") {
    let endIdx = -1;
    for (let i = 1; i < lines.length; i++) {
      if (lines[i] === "---" || lines[i] === "...") {
        endIdx = i;
        break;
      }
    }
    if (endIdx !== -1) {
      const frontmatterLines = lines.slice(0, endIdx + 1);
      const bodyLines = lines.slice(endIdx + 1);
      return {
        frontmatter: frontmatterLines.join("\n"),
        body: bodyLines.join("\n"),
      };
    }
  }
  return { frontmatter: null, body: rawContent };
}

const markdownComponents = {
  h1: ({ node, ...props }: any) => <h1 className="text-xl font-bold text-slate-900 mt-6 mb-2 border-b border-slate-200 pb-1" {...props} />,
  h2: ({ node, ...props }: any) => <h2 className="text-lg font-semibold text-slate-900 mt-5 mb-2" {...props} />,
  h3: ({ node, ...props }: any) => <h3 className="text-base font-semibold text-slate-800 mt-4 mb-2" {...props} />,
  h4: ({ node, ...props }: any) => <h4 className="text-sm font-semibold text-slate-800 mt-3 mb-1" {...props} />,
  p: ({ node, ...props }: any) => <p className="text-sm text-slate-800 my-2 leading-relaxed break-words" {...props} />,
  ul: ({ node, ...props }: any) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm text-slate-800" {...props} />,
  ol: ({ node, ...props }: any) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm text-slate-800" {...props} />,
  li: ({ node, ...props }: any) => <li className="text-sm" {...props} />,
  blockquote: ({ node, ...props }: any) => (
    <blockquote className="border-l-4 border-slate-300 bg-slate-50 pl-4 py-1 pr-2 my-2 text-slate-600 italic rounded-r" {...props} />
  ),
  pre: ({ node, ...props }: any) => (
    <pre className="bg-slate-50 border border-slate-200 rounded p-3 my-2 overflow-x-auto text-xs font-mono text-slate-800" {...props} />
  ),
  code: ({ node, inline, className, children, ...props }: any) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code className="bg-slate-100 text-slate-900 px-1.5 py-0.5 rounded text-xs font-mono border border-slate-200" {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  table: ({ node, ...props }: any) => (
    <div className="overflow-x-auto my-4 rounded border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-sm text-slate-800" {...props} />
    </div>
  ),
  thead: ({ node, ...props }: any) => <thead className="bg-slate-50 text-xs text-slate-700 uppercase font-medium" {...props} />,
  tbody: ({ node, ...props }: any) => <tbody className="divide-y divide-slate-200" {...props} />,
  tr: ({ node, ...props }: any) => <tr className="hover:bg-slate-50/50" {...props} />,
  th: ({ node, ...props }: any) => <th className="px-3 py-2 text-left font-semibold border-b border-slate-200" {...props} />,
  td: ({ node, ...props }: any) => <td className="px-3 py-2 text-slate-600" {...props} />,
  a: ({ node, href, children, ...props }: any) => {
    const isExternal = href?.startsWith("http://") || href?.startsWith("https://");
    return (
      <a
        href={href}
        className="text-indigo-600 hover:text-indigo-800 underline break-all"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
        {...props}
      >
        {children}
      </a>
    );
  }
};

export default function VaultSearchDetailPanel({ hit, notify }: VaultSearchDetailPanelProps) {
  const meta = hit.metadata;
  const relativePath = meta.relative_path;

  const [content, setContent] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!relativePath) {
      setContent("");
      setError("相対パスが不足しているため、ノートの全文を取得できません");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setContent("");

    getVaultFile(relativePath, controller.signal)
      .then((res) => {
        setContent(res.content);
        setError(null);
      })
      .catch((err) => {
        if (err.name === "AbortError" || controller.signal.aborted) {
          return;
        }
        setError(err.message || "ノートの取得に失敗しました");
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
    const url = buildObsidianUrl(hit);
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
            <tr>
              <td className="pr-3 font-medium w-20">Score</td>
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
            <div className="prose prose-slate max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {body}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

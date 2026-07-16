import { useEffect, useRef, useState } from "react";
import { searchVault, ApiError } from "../../api/client";
import type { VaultSearchHit } from "../../api/types";
import { formatScore } from "./utils";

export interface VaultSearchListProps {
  query: string;
  k: number;
  mode: "hybrid" | "keyword" | "similarity";
  refreshKey: number;
  onSelect: (hit: VaultSearchHit) => void;
  onLoaded: (items: VaultSearchHit[], error: string | null) => void;
}

export default function VaultSearchList({
  query,
  k,
  mode,
  refreshKey,
  onSelect,
  onLoaded,
}: VaultSearchListProps) {
  const [items, setItems] = useState<VaultSearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!query) {
      setItems([]);
      setError(null);
      setLoading(false);
      onLoaded([], null);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    searchVault({ q: query, k, mode })
      .then((res) => {
        if (controller.signal.aborted) return;
        setItems(res.items);
        onLoaded(res.items, null);
      })
      .catch((e) => {
        if (controller.signal.aborted) return;
        const msg = e instanceof ApiError ? e.message : "検索に失敗しました";
        setError(msg);
        setItems([]);
        onLoaded([], msg);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [query, k, mode, refreshKey, onLoaded]);

  if (!query) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-slate-500">
        検索クエリを入力して「検索」ボタンを押してください
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-sm text-slate-500">
        検索中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-sm text-red-600">{error}</div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 bg-white p-3 text-sm text-slate-500">
        {items.length} 件
      </div>
      <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {items.map((hit, i) => (
          <li key={`${hit.metadata.file_path}-${hit.metadata.chunk_index ?? i}`}>
            <button
              type="button"
              className="block w-full p-3 text-left hover:bg-slate-50"
              onClick={() => onSelect(hit)}
            >
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span className="font-mono">{formatScore(hit.score)}</span>
                <span className="truncate">{hit.metadata.relative_path || hit.metadata.file_path || "?"}</span>
              </div>
              <p className="mt-1 line-clamp-3 text-sm text-slate-800">
                {hit.content}
              </p>
            </button>
          </li>
        ))}
        {items.length === 0 && (
          <li className="p-6 text-sm text-slate-500">該当する結果はありません。</li>
        )}
      </ul>
    </div>
  );
}

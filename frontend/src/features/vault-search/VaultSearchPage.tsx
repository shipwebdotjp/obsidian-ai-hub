import { useCallback, useEffect, useState } from "react";
import VaultSearchList from "./VaultSearchList";
import VaultSearchDetailPanel from "./VaultSearchDetailPanel";
import type { VaultSearchHit } from "../../api/types";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

interface SearchHistoryItem {
  query: string;
  mode: "hybrid" | "keyword" | "similarity";
  k: number;
  searchedAt: string;
}

const HISTORY_KEY = "obsidian-ai-hub:vault-search-history:v1";
const MAX_HISTORY = 20;

function loadHistory(): SearchHistoryItem[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function persistHistory(history: SearchHistoryItem[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

export default function VaultSearchPage() {
  const [queryInput, setQueryInput] = useState("");
  const [mode, setMode] = useState<"hybrid" | "keyword" | "similarity">("hybrid");
  const [k, setK] = useState(10);
  const [committedQuery, setCommittedQuery] = useState("");
  const [committedMode, setCommittedMode] = useState<"hybrid" | "keyword" | "similarity">("hybrid");
  const [committedK, setCommittedK] = useState(10);
  const [selectedHit, setSelectedHit] = useState<VaultSearchHit | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>(loadHistory);

  useEffect(() => {
    persistHistory(searchHistory);
  }, [searchHistory]);

  const notify = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  const runSearch = useCallback((query: string, searchMode: "hybrid" | "keyword" | "similarity", resultK: number) => {
    if (!query.trim() || isSearching) return;
    setCommittedQuery(query.trim());
    setCommittedMode(searchMode);
    setCommittedK(resultK);
    setSelectedHit(null);
    setIsSearching(true);

    setSearchHistory((prev) => {
      const filtered = prev.filter(
        (h) => !(h.query === query.trim() && h.mode === searchMode && h.k === resultK)
      );
      const updated = [
        { query: query.trim(), mode: searchMode, k: resultK, searchedAt: new Date().toISOString() },
        ...filtered,
      ].slice(0, MAX_HISTORY);
      return updated;
    });

    setRefreshKey((v) => v + 1);
  }, [isSearching]);

  const handleSearch = useCallback(() => {
    if (isSearching) return;
    if (!queryInput.trim()) {
      notify("検索クエリを入力してください", "error");
      return;
    }
    runSearch(queryInput.trim(), mode, k);
  }, [queryInput, mode, k, notify, runSearch, isSearching]);

  const handleHistorySearch = useCallback((item: SearchHistoryItem) => {
    setQueryInput(item.query);
    setMode(item.mode);
    setK(item.k);
    runSearch(item.query, item.mode, item.k);
  }, [runSearch]);

  const handleLoaded = useCallback((items: VaultSearchHit[], error: string | null) => {
    setIsSearching(false);
    if (error) {
      notify(error, "error");
      return;
    }
    if (committedQuery && items.length === 0) {
      notify("検索結果が見つかりませんでした", "info");
    }
  }, [committedQuery, notify]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white p-3">
        <h1 className="text-base font-semibold">Vault 検索</h1>
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          placeholder="検索クエリ"
          className="min-w-[200px] rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value as "hybrid" | "keyword" | "similarity")}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="hybrid">Hybrid</option>
          <option value="keyword">Keyword</option>
          <option value="similarity">Similarity</option>
        </select>
        <select
          value={k}
          onChange={(e) => setK(Number(e.target.value))}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value={5}>5件</option>
          <option value={10}>10件</option>
          <option value={20}>20件</option>
          <option value={50}>50件</option>
        </select>
        <button
          type="button"
          onClick={handleSearch}
          disabled={isSearching || !queryInput.trim()}
          className="rounded bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {isSearching ? "検索中…" : "検索"}
        </button>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div className="flex w-1/2 flex-col border-r border-slate-200 overflow-hidden">
          {searchHistory.length > 0 && (
            <div className="shrink-0 max-h-36 overflow-y-auto border-b border-slate-100 p-2">
              <h2 className="mb-1 text-xs font-semibold text-slate-500">最近の検索</h2>
              <ul className="space-y-0.5">
                {searchHistory.map((item, i) => (
                  <li key={`${item.query}-${item.mode}-${item.k}-${item.searchedAt}`}>
                    <button
                      type="button"
                      onClick={() => handleHistorySearch(item)}
                      disabled={isSearching}
                      className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-slate-100 disabled:opacity-50"
                    >
                      <span className="truncate text-slate-700">{item.query}</span>
                      <span className="shrink-0 text-xs text-slate-400">{item.mode} / {item.k}件</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex-1 overflow-hidden">
            <VaultSearchList
              query={committedQuery}
              k={committedK}
              mode={committedMode}
              refreshKey={refreshKey}
              onSelect={setSelectedHit}
              onLoaded={handleLoaded}
            />
          </div>
        </div>
        <div className="w-1/2 overflow-hidden">
          {selectedHit ? (
            <VaultSearchDetailPanel hit={selectedHit} notify={notify} />
          ) : (
            <p className="p-6 text-sm text-slate-500">左の一覧から結果を選択してください。</p>
          )}
        </div>
      </div>
      <div className="pointer-events-none fixed bottom-4 right-4 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded px-4 py-2 text-sm text-white shadow ${
              t.kind === "error" ? "bg-rose-600" : "bg-slate-900"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

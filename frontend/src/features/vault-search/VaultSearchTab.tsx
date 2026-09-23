import { useCallback, useEffect, useState } from "react";
import VaultSearchList from "./VaultSearchList";
import VaultNoteDetailPanel from "./VaultNoteDetailPanel";
import MasterDetailLayout from "../../components/MasterDetailLayout";
import { DEFAULT_LIST_RATIO } from "../../hooks/usePaneResize";
import type { VaultSearchHit } from "../../api/types";

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

export interface VaultSearchTabProps {
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function VaultSearchTab({ notify }: VaultSearchTabProps) {
  const [queryInput, setQueryInput] = useState("");
  const [mode, setMode] = useState<"hybrid" | "keyword" | "similarity">("hybrid");
  const [k, setK] = useState(10);
  const [committedQuery, setCommittedQuery] = useState("");
  const [committedMode, setCommittedMode] = useState<"hybrid" | "keyword" | "similarity">("hybrid");
  const [committedK, setCommittedK] = useState(10);
  const [selectedHit, setSelectedHit] = useState<VaultSearchHit | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>(loadHistory);

  useEffect(() => {
    persistHistory(searchHistory);
  }, [searchHistory]);

  useEffect(() => {
    if (!selectedHit) setMobileDetailOpen(false);
  }, [selectedHit]);

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
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-3 sm:gap-3 sm:p-4">
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          placeholder="検索クエリ"
          className="w-full min-w-0 rounded border border-slate-300 px-2 py-1 text-sm sm:w-auto sm:min-w-[200px] sm:flex-1"
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
          className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {isSearching ? "検索中…" : "検索"}
        </button>
      </header>
      <MasterDetailLayout
        mobileOpen={mobileDetailOpen}
        onBack={() => setMobileDetailOpen(false)}
        mobileTitle="検索結果プレビュー"
        listClassName="w-full overflow-hidden border-slate-200 lg:w-[var(--pane-size)]"
        detailClassName="w-full min-w-0 overflow-hidden lg:flex-1"
        detailContentClassName="flex-1 overflow-hidden"
        paneOptions={{
          defaultSize: DEFAULT_LIST_RATIO,
          minSize: 300,
          minOther: 360,
          storageKey: "vault-search",
        }}
        list={
          <>
            {searchHistory.length > 0 && (
              <div className="max-h-36 shrink-0 overflow-y-auto border-b border-slate-100 p-2">
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
                onSelect={(h) => {
                  setSelectedHit(h);
                  setMobileDetailOpen(true);
                }}
                onLoaded={handleLoaded}
              />
            </div>
          </>
        }
        detail={
          selectedHit?.metadata.relative_path ? (
            <VaultNoteDetailPanel
              relativePath={selectedHit.metadata.relative_path}
              score={selectedHit.score}
              chunkIndex={selectedHit.metadata.chunk_index}
              mtime={selectedHit.metadata.mtime}
              notify={notify}
            />
          ) : (
            <p className="p-6 text-sm text-slate-500">一覧から結果を選択してください。</p>
          )
        }
      />
    </div>
  );
}

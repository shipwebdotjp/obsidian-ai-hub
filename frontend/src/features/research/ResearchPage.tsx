import { useCallback, useEffect, useState } from "react";
import ResearchList from "./ResearchList";
import ResearchDetailPanel from "./ResearchDetailPanel";
import type { ResearchTheme, ResearchStatus } from "../../api/types";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

export default function ResearchPage() {
  const [status, setStatus] = useState<string>("");
  const [queryInput, setQueryInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedTheme, setSelectedTheme] = useState<ResearchTheme | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const handleRefresh = useCallback(() => setRefreshKey((v) => v + 1), []);

  const onChanged = useCallback((_theme: ResearchTheme | null) => {
    handleRefresh();
  }, [handleRefresh]);

  const notify = useCallback((text: string, kind: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, text, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3500);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(queryInput);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [queryInput]);

  useEffect(() => {
    setSelectedTheme(null);
  }, [status, debouncedQuery]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white p-3">
        <h1 className="text-base font-semibold">リサーチ</h1>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべて</option>
          <option value="candidate">候補</option>
          <option value="approved">承認済み</option>
          <option value="rejected">却下済み</option>
          <option value="duplicate">重複</option>
        </select>
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="検索 (テーマ / direction)"
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <button
          type="button"
          onClick={() => setRefreshKey((v) => v + 1)}
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          再読み込み
        </button>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-1/2 border-r border-slate-200">
          <ResearchList
            status={status}
            query={debouncedQuery}
            onSelect={setSelectedTheme}
            refreshKey={refreshKey}
            notify={notify}
          />
        </div>
        <div className="w-1/2 overflow-hidden">
          {selectedTheme ? (
            <ResearchDetailPanel
              key={selectedTheme.theme_id}
              themeId={selectedTheme.theme_id}
              onChanged={onChanged}
              notify={notify}
            />
          ) : (
            <p className="p-6 text-sm text-slate-500">左の一覧からテーマを選択してください。</p>
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

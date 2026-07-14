import { useCallback, useEffect, useState } from "react";
import MemoryList from "./MemoryList";
import MemoryDetailPanel from "./MemoryDetailPanel";
import type { Memory, MemoryDetail, MemoryStatus } from "../../api/types";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

export default function MemoryPage() {
  const [status, setStatus] = useState<MemoryStatus>("candidate");
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const handleRefresh = useCallback(() => setRefreshKey((v) => v + 1), []);

  const onChanged = useCallback((memory: MemoryDetail | null) => {
    if (memory === null) {
      setSelectedMemory(null);
    }
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
    setSelectedMemory(null);
    setSelected(new Set());
  }, [status]);

  const showRightPanel = status === "candidate" || status === "approved" || status === "rejected";

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-slate-200 bg-white p-3">
        <h1 className="text-base font-semibold">メモリ</h1>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value as MemoryStatus)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="candidate">候補</option>
          <option value="approved">承認済み</option>
          <option value="rejected">却下済み</option>
          <option value="expired">期限切れ</option>
        </select>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="検索 (本文 / タグ)"
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="トピック"
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
          <MemoryList
            status={status}
            query={query}
            topic={topic}
            selectedIds={selected}
            onSelectionChange={setSelected}
            onSelect={setSelectedMemory}
            refreshKey={refreshKey}
            notify={notify}
          />
        </div>
        <div className="w-1/2 overflow-hidden">
          {selectedMemory ? (
            showRightPanel ? (
              <MemoryDetailPanel
                key={selectedMemory.memory_id}
                memoryId={selectedMemory.memory_id}
                status={status}
                onChanged={onChanged}
                notify={notify}
              />
            ) : (
              <p className="p-6 text-sm text-slate-500">
                このステータスの記憶は読み取り専用です。
              </p>
            )
          ) : (
            <p className="p-6 text-sm text-slate-500">左の一覧から候補を選択してください。</p>
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

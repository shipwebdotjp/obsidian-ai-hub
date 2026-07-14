import { useCallback, useEffect, useState } from "react";
import MemoryList from "./MemoryList";
import MemoryDetailPanel from "./MemoryDetailPanel";
import type { Memory, MemoryDetail, MemoryStatus } from "../../api/types";
import { getMemoryOptions, renderCopilotProfile } from "../../api/client";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

export default function MemoryPage() {
  const [status, setStatus] = useState<MemoryStatus>("candidate");
  const [queryInput, setQueryInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [kind, setKind] = useState("");
  const [topic, setTopic] = useState("");
  const [kindsOptions, setKindsOptions] = useState<string[]>([]);
  const [topicsOptions, setTopicsOptions] = useState<string[]>([]);
  const [isRendering, setIsRendering] = useState(false);

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

  // Fetch filter options once on page load
  useEffect(() => {
    getMemoryOptions()
      .then((res) => {
        setKindsOptions(res.kinds);
        setTopicsOptions(res.topics);
      })
      .catch((err) => {
        console.error("Failed to fetch memory options:", err);
      });
  }, []);

  // Debounce free-text search (Local input responds immediately, updates debounced value after 500ms)
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(queryInput);
    }, 500);

    return () => {
      window.clearTimeout(timer);
    };
  }, [queryInput]);

  // Reset list selection and single selection when any filter changes
  useEffect(() => {
    setSelectedMemory(null);
    setSelected(new Set());
  }, [status, debouncedQuery, kind, topic]);

  const showRightPanel = status === "candidate" || status === "approved" || status === "rejected" || status === "superseded" || status === "expired";

  const handleRenderCopilotProfile = async () => {
    const confirmed = window.confirm(
      "Copilotプロファイルを生成します。LLMによる生成処理が実行され、Vault内の7つの生成ファイルが上書きされます。よろしいですか？"
    );
    if (!confirmed) return;

    setIsRendering(true);
    try {
      const res = await renderCopilotProfile();
      notify(`${res.updated_files.length} 個のファイルを更新しました`, "info");
    } catch (err: any) {
      const msg = err?.message || "Copilotプロファイルの生成に失敗しました";
      notify(msg, "error");
    } finally {
      setIsRendering(false);
    }
  };

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
          <option value="superseded">置換済み</option>
        </select>
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="検索 (本文 / タグ)"
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">種別: すべて</option>
          {kindsOptions.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <select
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">トピック: すべて</option>
          {topicsOptions.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setRefreshKey((v) => v + 1)}
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          再読み込み
        </button>
        <button
          type="button"
          onClick={handleRenderCopilotProfile}
          disabled={isRendering}
          className="rounded border border-slate-300 px-3 py-1 text-sm bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
        >
          {isRendering ? "生成中…" : "プロファイル生成"}
        </button>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-1/2 border-r border-slate-200">
          <MemoryList
            status={status}
            query={debouncedQuery}
            topic={topic}
            kind={kind}
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

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { ApiError, listMemories, batchReview, reviewMemory, batchDeleteMemories } from "../../api/client";
import type { Memory, MemoryStatus } from "../../api/types";
import { formatDateTime } from "../../utils/date";

export interface MemoryListProps {
  status: MemoryStatus;
  query: string;
  topic: string;
  kind?: string;
  selectedIds: Set<string>;
  selectedMemoryId: string | null;
  onSelectionChange: (next: Set<string>) => void;
  onSelect: (memory: Memory) => void;
  refreshKey: number;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function MemoryList({
  status,
  query,
  topic,
  kind,
  selectedIds,
  selectedMemoryId,
  onSelectionChange,
  onSelect,
  refreshKey,
  notify,
}: MemoryListProps) {
  const [items, setItems] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const res = await listMemories({ status, q: query, topic, kind });
      if (controller.signal.aborted) return;
      setItems(res.items);
      onSelectionChange(new Set());
    } catch (e) {
      if (controller.signal.aborted) return;
      const msg = e instanceof ApiError ? e.message : "一覧取得に失敗しました";
      setError(msg);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [status, query, topic, kind, onSelectionChange]);

  useEffect(() => {
    void reload();
    return () => {
      abortRef.current?.abort();
    };
  }, [reload, refreshKey]);

  const allSelected = useMemo(
    () => items.length > 0 && items.every((m) => selectedIds.has(m.memory_id)),
    [items, selectedIds],
  );

  function toggleAll() {
    if (allSelected) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(items.map((m) => m.memory_id)));
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onSelectionChange(next);
  }

  async function batch(action: "approve" | "reject") {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`${selectedIds.size} 件を一括${action === "approve" ? "承認" : "却下"}します。よろしいですか？`)) {
      return;
    }
    setIsProcessing(new Set(selectedIds));
    try {
      const res = await batchReview({ memory_ids: Array.from(selectedIds), action });
      const missing = res.not_found.length;
      notify(
        `${res.updated.length} 件を${action === "approve" ? "承認" : "却下"}しました` +
          (missing ? `（未検出 ${missing} 件）` : ""),
      );
      await reload();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "一括操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsProcessing(new Set());
    }
  }

  async function batchDelete() {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`${selectedIds.size} 件を完全に削除しますか？この操作は取り消せません。`)) return;
    setIsProcessing(new Set(selectedIds));
    try {
      const res = await batchDeleteMemories({ memory_ids: Array.from(selectedIds) });
      const missing = res.not_found.length;
      notify(
        `${res.deleted.length} 件を削除しました` + (missing ? `（未検出 ${missing} 件）` : ""),
      );
      await reload();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "一括削除に失敗しました";
      notify(msg, "error");
    } finally {
      setIsProcessing(new Set());
    }
  }

  async function quickAction(id: string, action: "approve" | "reject") {
    setIsProcessing(new Set([id]));
    try {
      await reviewMemory(id, action);
      notify(`${id} を${action === "approve" ? "承認" : "却下"}しました`);
      await reload();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsProcessing(new Set());
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-3">
        <div className="flex items-center gap-2 text-sm">
          <label className="flex cursor-pointer items-center gap-1">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              disabled={items.length === 0}
              className="cursor-pointer disabled:cursor-not-allowed"
            />
            <span>全選択</span>
          </label>
          <span className="text-slate-500">({items.length} 件)</span>
        </div>
        <div className="flex gap-2">
            <button
              type="button"
              disabled={selectedIds.size === 0 || isProcessing.size > 0}
              onClick={() => batch("approve")}
              className="cursor-pointer rounded bg-emerald-600 px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isProcessing.size > 0 ? "処理中…" : "一括承認"}
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || isProcessing.size > 0}
              onClick={() => batch("reject")}
              className="cursor-pointer rounded bg-rose-600 px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isProcessing.size > 0 ? "処理中…" : "一括却下"}
            </button>
            <button
              type="button"
              disabled={selectedIds.size === 0 || isProcessing.size > 0}
              onClick={batchDelete}
              className="cursor-pointer rounded bg-rose-900 px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isProcessing.size > 0 ? "処理中…" : "一括削除"}
            </button>
        </div>
      </div>
      {loading && <p className="p-4 text-sm text-slate-500">読み込み中…</p>}
      {error && <p className="p-4 text-sm text-red-600">{error}</p>}
      <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {items.map((m) => {
          const checked = selectedIds.has(m.memory_id);
          const isSelected = selectedMemoryId === m.memory_id;
          return (
            <li
              key={m.memory_id}
              data-testid="memory-row"
              data-selected={isSelected ? "true" : "false"}
              className={`flex items-start gap-2 p-3 ${isSelected ? "bg-slate-200 border-l-4 border-slate-800" : checked ? "bg-slate-100" : "hover:bg-slate-50"}`}
            >
              <input
                type="checkbox"
                className="mt-1 cursor-pointer"
                checked={checked}
                onChange={() => toggleOne(m.memory_id)}
              />
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  className="block w-full cursor-pointer text-left"
                  onClick={() => onSelect(m)}
                >
                  <div className="text-sm">{m.content}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
                    <span className="rounded bg-slate-200 px-1">{m.kind || "?"}</span>
                    {m.memory_key && <span>key: {m.memory_key}</span>}
                    {typeof m.extraction_confidence === "number" && (
                      <span>conf: {m.extraction_confidence.toFixed(2)}</span>
                    )}
                    {m.created_at && <span>{formatDateTime(m.created_at)}</span>}
                  </div>
                  {(m.dedup_suggestions || []).length > 0 && (
                    <p className="mt-1 text-xs text-amber-700">
                      重複/置換提案: {m.dedup_suggestions.map((s) => `${s.relation}→${s.target_memory_id}`).join(", ")}
                    </p>
                  )}
                </button>
              </div>
              {status === "candidate" && (
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    onClick={() => quickAction(m.memory_id, "approve")}
                    disabled={isProcessing.has(m.memory_id)}
                    className="cursor-pointer rounded bg-emerald-600 px-2 py-0.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isProcessing.has(m.memory_id) ? "…" : "承認"}
                  </button>
                  <button
                    type="button"
                    onClick={() => quickAction(m.memory_id, "reject")}
                    disabled={isProcessing.has(m.memory_id)}
                    className="cursor-pointer rounded bg-rose-600 px-2 py-0.5 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isProcessing.has(m.memory_id) ? "…" : "却下"}
                  </button>
                </div>
              )}
            </li>
          );
        })}
        {!loading && items.length === 0 && (
          <li className="p-6 text-sm text-slate-500">該当する候補はありません。</li>
        )}
      </ul>
    </div>
  );
}

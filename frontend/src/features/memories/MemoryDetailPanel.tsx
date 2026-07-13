import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getMemory, reviewMemory } from "../../api/client";
import type { MemoryDetail } from "../../api/types";
import type { Memory } from "../../api/types";
import MemoryEditForm from "./MemoryEditForm";

export interface MemoryDetailPanelProps {
  memoryId: string;
  status: string;
  onChanged: (memory: MemoryDetail | null) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function MemoryDetailPanel({
  memoryId,
  status,
  onChanged,
  notify,
}: MemoryDetailPanelProps) {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const fetchIdRef = useRef(0);

  useEffect(() => {
    const currentFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    setEditing(false);
    getMemory(memoryId)
      .then((d) => {
        if (currentFetchId !== fetchIdRef.current) return;
        setDetail(d);
        onChanged(d);
      })
      .catch((e) => {
        if (currentFetchId !== fetchIdRef.current) return;
        const msg = e instanceof ApiError ? e.message : "詳細取得に失敗しました";
        setError(msg);
        setDetail(null);
      })
      .finally(() => {
        if (currentFetchId === fetchIdRef.current) setLoading(false);
      });
  }, [memoryId, onChanged]);

  const handleUpdated = useCallback(
    (m: Memory) => {
      setDetail((prev) => (prev ? { ...prev, ...m } : prev));
      setEditing(false);
      onChanged({ ...(detail || (m as MemoryDetail)), ...m } as MemoryDetail);
    },
    [detail, onChanged],
  );

  async function act(action: "approve" | "reject") {
    setIsSubmitting(true);
    try {
      await reviewMemory(memoryId, action);
      const updated = await getMemory(memoryId);
      setDetail(updated);
      notify(`${memoryId} を${action === "approve" ? "承認" : "却下"}しました`);
      onChanged(updated);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (loading) {
    return <p className="p-6 text-sm text-slate-500">読み込み中…</p>;
  }
  if (error) {
    return <p className="p-6 text-sm text-red-600">{error}</p>;
  }
  if (!detail) {
    return null;
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="rounded bg-slate-200 px-1">{detail.kind || "?"}</span>
        <span>status: {detail.status}</span>
        {detail.memory_key && <span>key: {detail.memory_key}</span>}
        {detail.stability && <span>stability: {detail.stability}</span>}
        {typeof detail.extraction_confidence === "number" && (
          <span>conf: {detail.extraction_confidence.toFixed(2)}</span>
        )}
      </div>
      <h2 className="text-sm font-semibold text-slate-700">本文</h2>
      <p className="mt-1 whitespace-pre-wrap text-sm">{detail.content}</p>

      {(detail.evidence || []).length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">根拠</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {detail.evidence.map((ev, i) => (
              <li key={i} className="rounded border border-slate-200 p-2">
                <div className="text-xs text-slate-500">{ev.path}</div>
                {ev.quote && <div className="mt-1">「{ev.quote}」</div>}
                {ev.observed_at && <div className="mt-1 text-xs text-slate-500">{ev.observed_at}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {(detail.dedup_suggestions || []).length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">重複・置換提案</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {detail.dedup_suggestions.map((s, i) => (
              <li key={i} className="rounded border border-amber-200 bg-amber-50 p-2">
                <div>
                  {s.relation} → {s.target_memory_id}
                  {typeof s.score === "number" && ` (${s.score})`}
                </div>
                {s.reason && <div className="text-xs text-slate-600">{s.reason}</div>}
              </li>
            ))}
          </ul>
        </>
      )}

      {(detail.events || []).length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">来歴</h2>
          <ul className="mt-1 space-y-1 text-xs text-slate-600">
            {detail.events.map((e) => (
              <li key={e.event_id} className="rounded border border-slate-200 p-2">
                <div>
                  {e.occurred_at} / {e.event_type} ({e.previous_status || "-"} → {e.new_status || "-"})
                </div>
                {e.reason && <div>reason: {e.reason}</div>}
                {e.changes && Object.keys(e.changes).length > 0 && (
                  <pre className="mt-1 whitespace-pre-wrap rounded bg-slate-50 p-1 text-[11px]">
                    {JSON.stringify(e.changes, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <div className="mt-6 space-y-3">
        {!editing ? (
          <div className="flex gap-2">
            {detail.status === "candidate" && (
              <>
                <button
                  type="button"
                  onClick={() => act("approve")}
                  disabled={isSubmitting}
                  className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                >
                  {isSubmitting ? "処理中…" : "承認"}
                </button>
                <button
                  type="button"
                  onClick={() => act("reject")}
                  disabled={isSubmitting}
                  className="rounded bg-rose-600 px-3 py-1 text-sm text-white disabled:opacity-50"
                >
                  {isSubmitting ? "処理中…" : "却下"}
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={isSubmitting}
              className="rounded bg-slate-900 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              編集して承認
            </button>
          </div>
        ) : (
          <MemoryEditForm
            memory={detail}
            onUpdated={handleUpdated}
            notify={notify}
            onCancel={() => setEditing(false)}
          />
        )}
      </div>
    </div>
  );
}

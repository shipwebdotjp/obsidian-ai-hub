import { useEffect, useState, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import {
  ApiError,
  listResearchThemes,
  rerunResearchTheme,
} from "../../api/client";
import type { ResearchTheme } from "../../api/types";
import { ROUTES } from "../../constants/routes";

export interface ResearchListProps {
  status: string;
  query: string;
  onSelect: (theme: ResearchTheme) => void;
  refreshKey: number;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function ResearchList({
  status,
  query,
  onSelect,
  refreshKey,
  notify,
}: ResearchListProps) {
  const [items, setItems] = useState<ResearchTheme[]>([]);
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
      const res = await listResearchThemes({
        status: status || undefined,
        q: query || undefined,
      });
      if (controller.signal.aborted) return;
      setItems(res.items);
    } catch (e) {
      if (controller.signal.aborted) return;
      const msg = e instanceof ApiError ? e.message : "一覧取得に失敗しました";
      setError(msg);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [status, query]);

  useEffect(() => {
    void reload();
    return () => {
      abortRef.current?.abort();
    };
  }, [reload, refreshKey]);

  const statusLabel = (s: string) => {
    switch (s) {
      case "candidate": return "候補";
      case "approved": return "承認済み";
      case "rejected": return "却下済み";
      case "duplicate": return "重複";
      default: return s;
    }
  };

  const jobStatusBadge = (s?: string) => {
    if (!s) return null;
    const colors: Record<string, string> = {
      pending: "bg-yellow-100 text-yellow-800",
      running: "bg-blue-100 text-blue-800",
      succeeded: "bg-emerald-100 text-emerald-800",
      failed: "bg-rose-100 text-rose-800",
    };
    return (
      <span className={`rounded px-1 text-[10px] font-medium ${colors[s] || "bg-slate-100"}`}>
        {s}
      </span>
    );
  };

  async function handleRerun(id: string) {
    setIsProcessing(new Set([id]));
    try {
      await rerunResearchTheme(id);
      notify("再実行を開始しました");
      await reload();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "再実行に失敗しました";
      notify(msg, "error");
    } finally {
      setIsProcessing(new Set());
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-3">
        <span className="text-sm text-slate-500">({items.length} 件)</span>
      </div>
      {loading && <p className="p-4 text-sm text-slate-500">読み込み中…</p>}
      {error && <p className="p-4 text-sm text-red-600">{error}</p>}
      <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {items.map((t) => {
          const job = t.latest_job;
          return (
            <li key={t.theme_id} className="flex items-start gap-2 p-3 hover:bg-slate-50">
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  className="block w-full text-left"
                  onClick={() => onSelect(t)}
                >
                  <div className="text-sm font-medium">{t.theme}</div>
                  {t.direction && (
                    <div className="text-xs text-slate-500 mt-0.5">{t.direction}</div>
                  )}
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="rounded bg-slate-200 px-1 text-[10px]">
                      {statusLabel(t.status)}
                    </span>
                    {t.kind && (
                      <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-600">
                        {t.kind}
                      </span>
                    )}
                    {job && jobStatusBadge(job.status)}
                    {t.duplicate_of_theme_id && (
                      <span className="text-[10px] text-amber-700">
                        重複先: {t.duplicate_of_theme_id}
                      </span>
                    )}
                    {t.related_theme_ids.length > 0 && (
                      <span className="text-[10px] text-blue-700">
                        related: {t.related_theme_ids.length}
                      </span>
                    )}
                  </div>
                </button>
              </div>
              {t.status === "candidate" && t.origin === "auto_suggestion" && t.hitl_run_id && (
                <div className="flex flex-col gap-1 shrink-0">
                  <Link
                    to={`${ROUTES.HITL}?run_id=${encodeURIComponent(t.hitl_run_id)}`}
                    className="rounded bg-blue-600 px-2 py-0.5 text-xs text-white text-center cursor-pointer"
                  >
                    確認待ち
                  </Link>
                </div>
              )}
              {job?.status === "failed" && (
                <button
                  type="button"
                  onClick={() => handleRerun(t.theme_id)}
                  disabled={isProcessing.has(t.theme_id)}
                  className="rounded bg-slate-600 px-2 py-0.5 text-xs text-white disabled:opacity-50 shrink-0"
                >
                  {isProcessing.has(t.theme_id) ? "…" : "再実行"}
                </button>
              )}
            </li>
          );
        })}
        {!loading && items.length === 0 && (
          <li className="p-6 text-sm text-slate-500">該当するテーマはありません。</li>
        )}
      </ul>
    </div>
  );
}

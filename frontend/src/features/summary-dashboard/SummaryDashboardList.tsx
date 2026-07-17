import { useEffect, useState, useCallback, useRef } from "react";
import { ApiError, listSummaries } from "../../api/client";
import type { SummaryListItem, SummaryPeriodType } from "../../api/types";

export interface SummaryDashboardListProps {
  periodType: string;
  period: string;
  topic: string;
  project: string;
  person: string;
  onSelect: (summary: SummaryListItem) => void;
  refreshKey: number;
}

export default function SummaryDashboardList({
  periodType,
  period,
  topic,
  project,
  person,
  onSelect,
  refreshKey,
}: SummaryDashboardListProps) {
  const [items, setItems] = useState<SummaryListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reload = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    try {
      const res = await listSummaries({
        period_type: (periodType as SummaryPeriodType) || undefined,
        period: period || undefined,
        topic: topic || undefined,
        project: project || undefined,
        person: person || undefined,
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
  }, [periodType, period, topic, project, person]);

  useEffect(() => {
    void reload();
    return () => {
      abortRef.current?.abort();
    };
  }, [reload, refreshKey]);

  const periodTypeLabel = (s: string) => {
    switch (s) {
      case "day":
        return "日次";
      case "week":
        return "週次";
      case "month":
        return "月次";
      default:
        return s;
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white p-3">
        <span className="text-sm text-slate-500">({items.length} 件)</span>
      </div>
      {loading && <p className="p-4 text-sm text-slate-500">読み込み中…</p>}
      {error && <p className="p-4 text-sm text-red-600">{error}</p>}
      <ul className="flex-1 divide-y divide-slate-100 overflow-y-auto">
        {items.map((s) => (
          <li key={s.summary_id}>
            <button
              type="button"
              onClick={() => onSelect(s)}
              className="block w-full p-3 text-left hover:bg-slate-50"
            >
              <div className="flex items-center gap-2">
                <span className="rounded bg-slate-200 px-1.5 text-[10px] font-medium">
                  {periodTypeLabel(s.period_type)}
                </span>
                <span className="text-xs text-slate-500">{s.period_key}</span>
              </div>
              <div className="mt-1 text-sm font-medium text-slate-800 line-clamp-2">
                {s.summary || "（サマリなし）"}
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {s.mood && (
                  <span className="rounded bg-blue-50 px-1.5 text-[10px] text-blue-700">
                    気分: {s.mood}
                  </span>
                )}
                {s.sleep_hours !== null && s.sleep_hours !== undefined && (
                  <span className="rounded bg-indigo-50 px-1.5 text-[10px] text-indigo-700">
                    睡眠: {s.sleep_hours}h
                  </span>
                )}
                {s.topics.slice(0, 3).map((t) => (
                  <span
                    key={t}
                    className="rounded bg-emerald-50 px-1.5 text-[10px] text-emerald-700"
                  >
                    {t}
                  </span>
                ))}
                {s.projects.slice(0, 3).map((p) => (
                  <span
                    key={p}
                    className="rounded bg-amber-50 px-1.5 text-[10px] text-amber-700"
                  >
                    {p}
                  </span>
                ))}
              </div>
            </button>
          </li>
        ))}
        {!loading && items.length === 0 && (
          <li className="p-6 text-sm text-slate-500">該当するサマリはありません。</li>
        )}
      </ul>
    </div>
  );
}

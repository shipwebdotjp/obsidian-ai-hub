import { useEffect, useRef, useState } from "react";
import { ApiError, getSummary } from "../../api/client";
import type { SummaryDetail } from "../../api/types";

export interface SummaryDashboardDetailProps {
  summaryId: string;
}

export default function SummaryDashboardDetail({
  summaryId,
}: SummaryDashboardDetailProps) {
  const [detail, setDetail] = useState<SummaryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchIdRef = useRef(0);

  useEffect(() => {
    const currentFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(null);

    getSummary(summaryId)
      .then((d) => {
        if (currentFetchId !== fetchIdRef.current) return;
        setDetail(d);
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
  }, [summaryId]);

  if (loading) {
    return <p className="p-6 text-sm text-slate-500">読み込み中…</p>;
  }
  if (error) {
    return <p className="p-6 text-sm text-red-600">{error}</p>;
  }
  if (!detail) {
    return null;
  }

  const itemsByKind = new Map<string, typeof detail.items>();
  for (const item of detail.items) {
    const list = itemsByKind.get(item.kind) || [];
    list.push(item);
    itemsByKind.set(item.kind, list);
  }

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

  const kindOrder = [
    "highlights",
    "activities",
    "tasks",
    "learnings",
    "challenges",
    "progress",
    "reflections",
    "next_actions",
    "plans",
    "focus",
    "risks",
  ];
  const sortedKinds = Array.from(itemsByKind.keys()).sort(
    (a, b) => (kindOrder.indexOf(a) ?? 99) - (kindOrder.indexOf(b) ?? 99)
  );

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
        <span className="rounded bg-slate-200 px-1.5 py-0.5 font-medium">
          {periodTypeLabel(detail.period_type)}
        </span>
        <span>{detail.period_key}</span>
        {detail.period_start &&
          detail.period_end &&
          detail.period_start !== detail.period_key && (
            <span>
              {detail.period_start} ～ {detail.period_end}
            </span>
          )}
      </div>

      <h2 className="text-base font-semibold text-slate-800">
        {detail.summary || "（サマリなし）"}
      </h2>

      <div className="mt-3 flex flex-wrap gap-2">
        {detail.mood && (
          <span className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">
            気分: {detail.mood}
          </span>
        )}
        {detail.sleep_hours !== null && detail.sleep_hours !== undefined && (
          <span className="rounded bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
            睡眠: {detail.sleep_hours}h
          </span>
        )}
        {detail.sleep_raw && (
          <span className="text-xs text-slate-400">({detail.sleep_raw})</span>
        )}
      </div>

      {detail.topics.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-500">トピック</h3>
          <div className="mt-1 flex flex-wrap gap-1">
            {detail.topics.map((t) => (
              <span
                key={t}
                className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {detail.projects.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-500">プロジェクト</h3>
          <div className="mt-1 flex flex-wrap gap-1">
            {detail.projects.map((p) => (
              <span
                key={p}
                className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700"
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      )}

      {detail.people.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-500">人物</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {detail.people.map((p) => (
              <li key={p.name} className="text-slate-700">
                <span className="font-medium">{p.name}</span>
                {p.note && (
                  <span className="ml-1 text-xs text-slate-500">{p.note}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.keywords.length > 0 && (
        <div className="mt-4">
          <h3 className="text-xs font-semibold text-slate-500">キーワード</h3>
          <div className="mt-1 flex flex-wrap gap-1">
            {detail.keywords.map((k) => (
              <span
                key={k}
                className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
              >
                {k}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-5 space-y-4">
        {sortedKinds.map((kind) => (
          <div key={kind}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {kind}
            </h3>
            <ul className="mt-1 space-y-2">
              {itemsByKind
                .get(kind)
                ?.sort((a, b) => a.display_order - b.display_order)
                .map((item) => (
                  <li
                    key={item.summary_item_id}
                    className="whitespace-pre-wrap rounded border border-slate-100 bg-slate-50 p-2 text-sm text-slate-700"
                  >
                    {item.body}
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

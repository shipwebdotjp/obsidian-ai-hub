import { useState } from "react";
import { getApiErrorMessage } from "../../utils/error";
import { Link } from "react-router-dom";
import { listResearchThemes, rerunResearchTheme } from "../../api/client";
import type { ResearchTheme } from "../../api/types";
import { ROUTES } from "../../constants/routes";
import { useListResource } from "../../hooks/useListResource";
import { researchJobStatusColor, researchStatusLabel } from "./researchLabels";

export interface ResearchListProps {
  status: string;
  query: string;
  onSelect: (theme: ResearchTheme) => void;
  onOpenTheme: (themeId: string) => void;
  refreshKey: number;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function ResearchList({
  status,
  query,
  onSelect,
  onOpenTheme,
  refreshKey,
  notify,
}: ResearchListProps) {
  const [isProcessing, setIsProcessing] = useState<Set<string>>(new Set());

  const { items, loading, error, reload } = useListResource<ResearchTheme>({
    fetcher: () =>
      listResearchThemes({
        status: status || undefined,
        q: query || undefined,
      }),
    deps: [status, query],
    refreshKey,
    fallbackError: "一覧取得に失敗しました",
  });

  const jobStatusBadge = (s?: string) => {
    if (!s) return null;
    return (
      <span className={`rounded px-1 text-[10px] font-medium ${researchJobStatusColor(s)}`}>
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
      const msg = getApiErrorMessage(e, "再実行に失敗しました");
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
                      {researchStatusLabel(t.status)}
                    </span>
                    {t.kind && (
                      <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-600">
                        {t.kind}
                      </span>
                    )}
                    {job && jobStatusBadge(job.status)}
                    {t.related_theme_ids.length > 0 && (
                      <span className="text-[10px] text-blue-700">
                        related: {t.related_theme_ids.length}
                      </span>
                    )}
                  </div>
                </button>
                {t.duplicate_of_theme ? (
                  <button
                    type="button"
                    onClick={() => onOpenTheme(t.duplicate_of_theme!.theme_id)}
                    aria-label={`重複先テーマ「${t.duplicate_of_theme.theme}」を開く`}
                    className="mt-1 text-left text-[10px] text-amber-700 underline cursor-pointer hover:text-amber-900"
                  >
                    重複先: {t.duplicate_of_theme.theme}
                  </button>
                ) : t.duplicate_of_theme_id ? (
                  <div className="mt-1 text-[10px] text-amber-700">
                    重複先テーマは見つかりません (ID: {t.duplicate_of_theme_id})
                  </div>
                ) : null}
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

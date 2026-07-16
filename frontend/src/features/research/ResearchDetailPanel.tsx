import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getResearchTheme, reviewResearchTheme, rerunResearchTheme } from "../../api/client";
import type { ResearchTheme } from "../../api/types";

export interface ResearchDetailPanelProps {
  themeId: string;
  onChanged: (theme: ResearchTheme | null) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function ResearchDetailPanel({
  themeId,
  onChanged,
  notify,
}: ResearchDetailPanelProps) {
  const [detail, setDetail] = useState<ResearchTheme | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [relatedThemes, setRelatedThemes] = useState<Map<string, string>>(new Map());
  const fetchIdRef = useRef(0);

  useEffect(() => {
    const currentFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(null);

    getResearchTheme(themeId)
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
  }, [themeId]);

  useEffect(() => {
    if (!detail?.related_theme_ids.length) {
      setRelatedThemes(new Map());
      return;
    }

    let cancelled = false;
    const fetchRelated = async () => {
      const results = await Promise.allSettled(
        detail.related_theme_ids.map((id) => getResearchTheme(id))
      );
      if (cancelled) return;
      const map = new Map<string, string>();
      results.forEach((r, i) => {
        if (r.status === "fulfilled") {
          map.set(detail.related_theme_ids[i], r.value.theme);
        }
      });
      setRelatedThemes(map);
    };
    fetchRelated().catch(() => {});
    return () => { cancelled = true; };
  }, [detail?.related_theme_ids]);

  async function handleAction(action: "approve" | "reject") {
    setIsSubmitting(true);
    try {
      await reviewResearchTheme(themeId, action);
      const updated = await getResearchTheme(themeId);
      setDetail(updated);
      notify(`${themeId} を${action === "approve" ? "承認" : "却下"}しました`);
      onChanged(updated);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "操作に失敗しました";
      notify(msg, "error");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRerun() {
    setIsSubmitting(true);
    try {
      await rerunResearchTheme(themeId);
      notify("再実行を開始しました");
      const updated = await getResearchTheme(themeId);
      setDetail(updated);
      onChanged(updated);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "再実行に失敗しました";
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

  const job = detail.latest_job;
  const statusLabel = (s: string) => {
    switch (s) {
      case "candidate": return "候補";
      case "approved": return "承認済み";
      case "rejected": return "却下済み";
      case "duplicate": return "重複";
      default: return s;
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="rounded bg-slate-200 px-1">{statusLabel(detail.status)}</span>
        {detail.kind && <span className="rounded bg-slate-200 px-1">{detail.kind}</span>}
        {detail.confidence !== undefined && (
          <span>conf: {detail.confidence.toFixed(2)}</span>
        )}
        {detail.created_at && <span>{detail.created_at}</span>}
      </div>

      <h2 className="text-sm font-semibold text-slate-700">テーマ</h2>
      <p className="mt-1 text-sm">{detail.theme}</p>

      {detail.direction && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">direction</h2>
          <p className="mt-1 text-sm">{detail.direction}</p>
        </>
      )}

      {detail.why_now && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">why_now</h2>
          <p className="mt-1 text-sm whitespace-pre-wrap">{detail.why_now}</p>
        </>
      )}

      {detail.duplicate_of_theme_id && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-amber-700">重複情報</h2>
          <div className="mt-1 rounded border border-amber-200 bg-amber-50 p-3 text-sm">
            <div>重複先: {detail.duplicate_of_theme_id}</div>
            {detail.duplicate_reason && <div className="mt-1 text-xs">理由: {detail.duplicate_reason}</div>}
          </div>
        </>
      )}

      {detail.related_theme_ids.length > 0 && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-blue-700">関連テーマ</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {detail.related_theme_ids.map((id) => (
              <li key={id} className="text-xs text-blue-600">
                {relatedThemes.get(id) || id}
              </li>
            ))}
          </ul>
        </>
      )}

      {job && (
        <>
          <h2 className="mt-4 text-sm font-semibold text-slate-700">調査</h2>
          <div className="mt-1 space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">状態:</span>
              <span className="text-xs font-medium">{job.status}</span>
              {job.mode && <span className="text-xs text-slate-500">mode: {job.mode}</span>}
              {job.generated_title && <span className="text-xs text-slate-500">{job.generated_title}</span>}
            </div>
            {job.error && (
              <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
                {job.error}
              </div>
            )}
            {job.markdown && job.status === "succeeded" && (
              <>
                <h3 className="text-xs font-semibold text-slate-700 mt-2">結果</h3>
                <pre className="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-xs">
                  {job.markdown.slice(0, 10000)}
                  {job.markdown.length > 10000 && "\n...(truncated)"}
                </pre>
              </>
            )}
          </div>
        </>
      )}

      <div className="mt-6 space-x-2">
        {detail.status === "candidate" && (
          <>
            <button
              type="button"
              onClick={() => handleAction("approve")}
              disabled={isSubmitting}
              className="rounded bg-emerald-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {isSubmitting ? "処理中…" : "承認"}
            </button>
            <button
              type="button"
              onClick={() => handleAction("reject")}
              disabled={isSubmitting}
              className="rounded bg-rose-600 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {isSubmitting ? "処理中…" : "却下"}
            </button>
          </>
        )}
        {job?.status === "failed" && (
          <button
            type="button"
            onClick={handleRerun}
            disabled={isSubmitting}
            className="rounded bg-slate-600 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {isSubmitting ? "処理中…" : "再実行"}
          </button>
        )}
      </div>
    </div>
  );
}

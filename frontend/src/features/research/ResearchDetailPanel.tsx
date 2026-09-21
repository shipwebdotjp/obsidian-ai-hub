import { useCallback, useEffect, useRef, useState } from "react";
import { getApiErrorMessage } from "../../utils/error";
import { Link } from "react-router-dom";
import { getResearchTheme, rerunResearchTheme } from "../../api/client";
import type { ResearchTheme } from "../../api/types";
import MarkdownPreview from "../../components/MarkdownPreview";
import { ROUTES } from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { researchJobStatusLabel, researchModeLabel, researchStatusLabel } from "./researchLabels";
import { parseResearchFrontmatter } from "./researchMarkdown";

export interface ResearchDetailPanelProps {
  themeId: string;
  refreshKey?: number;
  onChanged: (theme: ResearchTheme | null) => void;
  onOpenTheme: (themeId: string) => void;
  notify: (msg: string, kind?: "info" | "error") => void;
}

export default function ResearchDetailPanel({
  themeId,
  refreshKey = 0,
  onChanged,
  onOpenTheme,
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
        const msg = getApiErrorMessage(e, "詳細取得に失敗しました");
        setError(msg);
        setDetail(null);
      })
      .finally(() => {
        if (currentFetchId === fetchIdRef.current) setLoading(false);
      });
  }, [themeId, refreshKey]);

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

  async function handleRerun() {
    setIsSubmitting(true);
    try {
      await rerunResearchTheme(themeId);
      notify("再実行を開始しました");
      const updated = await getResearchTheme(themeId);
      setDetail(updated);
      onChanged(updated);
    } catch (e) {
      const msg = getApiErrorMessage(e, "再実行に失敗しました");
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
  const frontmatter = job?.markdown && job.status === "succeeded"
    ? parseResearchFrontmatter(job.markdown)
    : null;
  const resultBody = frontmatter?.body ?? (job?.status === "succeeded" ? job?.markdown : undefined);
  const resultTitle = job?.generated_title?.trim() || frontmatter?.title;
  const generatedAtRaw = frontmatter?.generated_at || job?.finished_at || job?.started_at;
  const generatedAt = generatedAtRaw ? formatDateTime(generatedAtRaw) : "";

  return (
    <div className="flex h-full flex-col overflow-y-auto p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="rounded bg-slate-200 px-1">{researchStatusLabel(detail.status)}</span>
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
            {detail.duplicate_of_theme ? (
              <button
                type="button"
                onClick={() => onOpenTheme(detail.duplicate_of_theme!.theme_id)}
                aria-label={`重複先テーマ「${detail.duplicate_of_theme.theme}」を開く`}
                className="text-left text-amber-800 underline cursor-pointer hover:text-amber-950"
              >
                重複先: {detail.duplicate_of_theme.theme}
              </button>
            ) : (
              <div>重複先テーマは見つかりません (ID: {detail.duplicate_of_theme_id})</div>
            )}
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
            <dl className="rounded border border-slate-200 bg-slate-50 p-3 text-xs space-y-1.5">
              <div className="flex items-center gap-2">
                <dt className="shrink-0 text-slate-500">状態</dt>
                <dd className="font-medium text-slate-800">{researchJobStatusLabel(job.status)}</dd>
                {job.mode && (
                  <dd className="rounded bg-indigo-100 px-1 text-[10px] text-indigo-800">
                    {researchModeLabel(job.mode)}
                  </dd>
                )}
              </div>
              {resultTitle && (
                <div className="flex items-start gap-2">
                  <dt className="shrink-0 text-slate-500">タイトル</dt>
                  <dd className="font-medium text-slate-800 break-words">{resultTitle}</dd>
                </div>
              )}
              {generatedAt && (
                <div className="flex items-center gap-2">
                  <dt className="shrink-0 text-slate-500">生成日時</dt>
                  <dd className="text-slate-700">{generatedAt}</dd>
                </div>
              )}
              {frontmatter?.source && (
                <div className="flex items-center gap-2">
                  <dt className="shrink-0 text-slate-500">source</dt>
                  <dd className="text-slate-700">{frontmatter.source}</dd>
                </div>
              )}
              {frontmatter?.output_style && (
                <div className="flex items-center gap-2">
                  <dt className="shrink-0 text-slate-500">output_style</dt>
                  <dd className="text-slate-700">{frontmatter.output_style}</dd>
                </div>
              )}
            </dl>
            {job.error && (
              <div className="rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
                {job.error}
              </div>
            )}
            {resultBody && job.status === "succeeded" && (
              <>
                <h3 className="text-xs font-semibold text-slate-700 mt-2">結果</h3>
                <MarkdownPreview content={resultBody} />
              </>
            )}
          </div>
        </>
      )}

      <div className="mt-6 space-x-2">
        {detail.status === "candidate" && detail.origin === "auto_suggestion" && detail.hitl_run_id && (
          <Link
            to={`${ROUTES.HITL}?run_id=${encodeURIComponent(detail.hitl_run_id)}`}
            className="inline-block rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 cursor-pointer"
          >
            HITLで回答
          </Link>
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

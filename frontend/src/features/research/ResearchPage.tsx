import { useCallback, useEffect, useState, useRef } from "react";
import ResearchList from "./ResearchList";
import ResearchDetailPanel from "./ResearchDetailPanel";
import type { ResearchTheme, ResearchStatus } from "../../api/types";
import { runResearchTheme, getResearchTheme, ApiError } from "../../api/client";

interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

interface TrackedJob {
  jobId: string;
  themeId: string;
  themeName: string;
  status: "pending" | "running" | "succeeded" | "failed";
}

export default function ResearchPage() {
  const [status, setStatus] = useState<string>("");
  const [queryInput, setQueryInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedTheme, setSelectedTheme] = useState<ResearchTheme | null>(null);
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [detailRefreshKey, setDetailRefreshKey] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [themeInput, setThemeInput] = useState("");
  const [modeInput, setModeInput] = useState<"auto" | "internal" | "web" | "deep">("auto");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  // Background Job Tracking State
  const [trackedJobs, setTrackedJobs] = useState<TrackedJob[]>([]);
  const trackedJobsRef = useRef<TrackedJob[]>([]);

  useEffect(() => {
    trackedJobsRef.current = trackedJobs;
  }, [trackedJobs]);

  const handleRefresh = useCallback(() => setRefreshKey((v) => v + 1), []);

  const onChanged = useCallback((updatedTheme: ResearchTheme | null) => {
    if (updatedTheme) {
      setSelectedTheme(updatedTheme);
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

  const openTheme = useCallback(async (themeId: string) => {
    try {
      const theme = await getResearchTheme(themeId);
      setSelectedTheme(theme);
      setMobileDetailOpen(true);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "テーマ詳細の取得に失敗しました";
      notify(msg, "error");
    }
  }, [notify]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(queryInput);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [queryInput]);

  useEffect(() => {
    setSelectedTheme(null);
    setMobileDetailOpen(false);
  }, [status, debouncedQuery]);

  useEffect(() => {
    if (!selectedTheme) setMobileDetailOpen(false);
  }, [selectedTheme]);

  // Poll active background jobs via sequential setTimeout (no overlapping, functional merge updates)
  useEffect(() => {
    let timerId: number | null = null;
    let isCancelled = false;

    const poll = async () => {
      const currentActive = trackedJobsRef.current.filter(
        (j: TrackedJob) => j.status === "pending" || j.status === "running"
      );

      if (currentActive.length === 0) {
        if (!isCancelled) {
          timerId = window.setTimeout(poll, 3000);
        }
        return;
      }

      for (const job of currentActive) {
        if (isCancelled) return;
        try {
          const latestTheme = await getResearchTheme(job.themeId);
          const latestJob = latestTheme.latest_job;

          let resolvedStatus: "pending" | "running" | "succeeded" | "failed" | null = null;
          let jobError: string | null = null;

          if (latestJob) {
            if (latestJob.job_id === job.jobId) {
              resolvedStatus = latestJob.status as any;
              jobError = latestJob.error || null;
            } else {
              resolvedStatus = "failed";
              jobError = "別のジョブにより上書きまたは終了されました";
            }
          }

          if (resolvedStatus && resolvedStatus !== job.status) {
            setTrackedJobs((prevJobs) =>
              prevJobs.map((j: TrackedJob) => {
                if (j.jobId === job.jobId) {
                  return { ...j, status: resolvedStatus! };
                }
                return j;
              })
            );

            if (resolvedStatus === "succeeded") {
              notify(`「${job.themeName}」の調査・保存・承認が完了しました`, "info");
            } else if (resolvedStatus === "failed") {
              const errMsg = jobError ? ` (${jobError})` : "";
              notify(`「${job.themeName}」の調査に失敗しました${errMsg}。詳細パネルから失敗原因を確認できます`, "error");
            }

            if (selectedTheme?.theme_id === job.themeId) {
              setSelectedTheme(latestTheme);
              setDetailRefreshKey((v) => v + 1);
            }

            handleRefresh();
          }
        } catch (e) {
          console.error("Failed to poll theme detail", e);
        }
      }

      if (!isCancelled) {
        timerId = window.setTimeout(poll, 3000);
      }
    };

    timerId = window.setTimeout(poll, 3000);

    return () => {
      isCancelled = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    };
  }, [selectedTheme, notify, handleRefresh]);

  const handleModalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!themeInput || !themeInput.trim()) {
      setModalError("テーマ名を入力してください");
      return;
    }

    setIsSubmitting(true);
    setModalError(null);

    try {
      const res = await runResearchTheme(themeInput.trim(), modeInput);

      // Select the theme in details panel immediately
      setSelectedTheme(res.theme);
      setMobileDetailOpen(true);

      // Track the job
      const newTracked: TrackedJob = {
        jobId: res.job.job_id,
        themeId: res.theme.theme_id,
        themeName: res.theme.theme,
        status: "pending",
      };
      setTrackedJobs((prev) => [...prev, newTracked]);

      // Close modal and reset fields
      setIsModalOpen(false);
      setThemeInput("");
      setModeInput("auto");

      // Trigger list refresh
      handleRefresh();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "リサーチの作成に失敗しました";
      setModalError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const closeModal = () => {
    if (isSubmitting) return;
    setIsModalOpen(false);
    setThemeInput("");
    setModeInput("auto");
    setModalError(null);
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white p-3 sm:gap-3 sm:p-4">
        <h1 className="text-base font-semibold">リサーチ</h1>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべて</option>
          <option value="candidate">候補</option>
          <option value="approved">承認済み</option>
          <option value="rejected">却下済み</option>
          <option value="duplicate">重複</option>
        </select>
        <input
          type="search"
          value={queryInput}
          onChange={(e) => setQueryInput(e.target.value)}
          placeholder="検索 (テーマ / direction)"
          className="w-full min-w-0 rounded border border-slate-300 px-2 py-1 text-sm sm:w-auto sm:flex-1"
        />
        <button
          type="button"
          onClick={() => setRefreshKey((v) => v + 1)}
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          再読み込み
        </button>
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="ml-auto rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700"
        >
          新規リサーチ
        </button>
      </header>
      <div className="flex flex-1 flex-col overflow-hidden lg:flex-row">
        <div
          className={`h-full w-full min-h-0 border-slate-200 lg:w-1/2 lg:border-r ${
            mobileDetailOpen ? "hidden" : "flex flex-col"
          } lg:flex lg:flex-col`}
        >
          <ResearchList
            status={status}
            query={debouncedQuery}
            onSelect={(t) => {
              setSelectedTheme(t);
              setMobileDetailOpen(true);
            }}
            onOpenTheme={openTheme}
            refreshKey={refreshKey}
            notify={notify}
          />
        </div>
        <div
          className={`h-full w-full min-h-0 overflow-hidden lg:w-1/2 ${
            mobileDetailOpen ? "flex flex-col" : "hidden"
          } lg:flex lg:flex-col`}
        >
          <div className="flex items-center gap-2 border-b border-slate-200 p-3 lg:hidden">
            <button
              type="button"
              onClick={() => setMobileDetailOpen(false)}
              aria-label="一覧に戻る"
              className="rounded px-2 py-1 text-sm text-slate-600 hover:bg-slate-100"
            >
              ← 一覧
            </button>
            <span className="truncate text-sm font-semibold text-slate-700">
              リサーチ詳細
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {selectedTheme ? (
              <ResearchDetailPanel
                themeId={selectedTheme.theme_id}
                refreshKey={detailRefreshKey}
                onChanged={onChanged}
                onOpenTheme={openTheme}
                notify={notify}
              />
            ) : (
              <p className="p-6 text-sm text-slate-500">一覧からテーマを選択してください。</p>
            )}
          </div>
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

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-slate-900">新規リサーチ</h2>
            <form onSubmit={handleModalSubmit} className="mt-4 space-y-4">
              <div>
                <label htmlFor="modal-theme" className="block text-xs font-medium text-slate-500">
                  テーマ
                </label>
                <input
                  id="modal-theme"
                  type="text"
                  required
                  disabled={isSubmitting}
                  value={themeInput}
                  onChange={(e) => setThemeInput(e.target.value)}
                  placeholder="テーマを入力してください"
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500"
                />
              </div>

              <div>
                <label htmlFor="modal-mode" className="block text-xs font-medium text-slate-500">
                  モード
                </label>
                <select
                  id="modal-mode"
                  disabled={isSubmitting}
                  value={modeInput}
                  onChange={(e) => setModeInput(e.target.value as any)}
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none disabled:bg-slate-50"
                >
                  <option value="auto">自動（router）</option>
                  <option value="internal">内省 (internal)</option>
                  <option value="web">ウェブ検索 (web)</option>
                  <option value="deep">ディープリサーチ (deep)</option>
                </select>
              </div>

              {modalError && (
                <div className="rounded border border-rose-200 bg-rose-50 p-3 text-xs text-rose-600">
                  {modalError}
                </div>
              )}

              <div className="mt-6 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={isSubmitting}
                  onClick={closeModal}
                  className="rounded border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  キャンセル
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                   className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {isSubmitting ? "実行中..." : "実行"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

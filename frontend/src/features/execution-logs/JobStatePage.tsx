import { useCallback, useEffect, useState } from "react";
import { listJobStates } from "../../api/client";
import type { JobState } from "../../api/types";
import { formatDateTime } from "../../utils/date";

const JOB_STATE_POLL_MS = 30_000;
const ERROR_WINDOW_MS = 60 * 60 * 1000; // last_error_at: show エラー for 1h
const ACTIVE_WINDOW_MS = 3 * 60 * 1000; // last_check_at: actively running
const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000; // last_check_at: seen recently

export default function JobStatePage() {
  const [jobStates, setJobStates] = useState<JobState[]>([]);
  const [jobStatesError, setJobStatesError] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchJobStates = useCallback(async () => {
    try {
      const res = await listJobStates();
      setJobStates(res.items);
      setJobStatesError(false);
    } catch {
      setJobStatesError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobStates();
    const interval = setInterval(fetchJobStates, JOB_STATE_POLL_MS);
    return () => clearInterval(interval);
  }, [fetchJobStates]);

  const isWithinMs = (iso: string | null | undefined, withinMs: number) => {
    if (!iso) return false;
    const t = new Date(iso).getTime();
    if (!Number.isFinite(t)) return false;
    const delta = Date.now() - t;
    return delta >= 0 && delta < withinMs;
  };

  const formatTs = (v: string | null | undefined) => (v ? formatDateTime(v) : "");

  const getJobStateHealth = (ts: JobState) => {
    if (isWithinMs(ts.last_error_at, ERROR_WINDOW_MS)) {
      return { label: "エラー", className: "bg-rose-50 text-rose-700 border-rose-200" };
    }
    if (isWithinMs(ts.last_check_at, ACTIVE_WINDOW_MS)) {
      return { label: "稼働中", className: "bg-emerald-50 text-emerald-700 border-emerald-200" };
    }
    if (isWithinMs(ts.last_check_at, RECENT_WINDOW_MS)) {
      return { label: "直近あり", className: "bg-amber-50 text-amber-700 border-amber-200" };
    }
    return { label: "停止", className: "bg-slate-50 text-slate-500 border-slate-200" };
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">ジョブ状態</h1>
        <p className="text-xs text-slate-500 mt-1">
          定期・高頻度ジョブの動作状態を確認できます（空振りはログに出さずここに集計）
        </p>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {jobStatesError && (
          <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3">
            <p className="text-xs font-semibold text-amber-700">
              ジョブ状態を取得できません
            </p>
          </div>
        )}

        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">読み込み中…</div>
        ) : jobStates.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            ジョブ状態データがありません。
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {jobStates.map((ts) => {
              const health = getJobStateHealth(ts);
              return (
                <div
                  key={ts.job_id}
                  className="flex flex-col gap-2 rounded border border-slate-200 bg-white p-4 shadow-sm"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-semibold text-slate-800 text-sm">
                      {ts.job_id}
                    </span>
                    <span
                      className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${health.className}`}
                    >
                      {health.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-600">
                    <span className="text-slate-400">最終確認</span>
                    <span>{formatTs(ts.last_check_at) || "-"}</span>
                    <span className="text-slate-400">空振り連続</span>
                    <span>{ts.consecutive_empty_count} 回</span>
                    <span className="text-slate-400">最終処理</span>
                    <span>{formatTs(ts.last_processed_at) || "-"}</span>
                    <span className="text-slate-400">直近の処理/スキップ/失敗</span>
                    <span>
                      {ts.processed_count} / {ts.skipped_count} / {ts.failed_count}
                    </span>
                  </div>
                  {ts.last_error_message && (
                    <div className="break-all rounded border border-rose-200 bg-rose-50 px-2 py-1 text-xs text-rose-700">
                      {ts.last_error_type ? `${ts.last_error_type}: ` : ""}
                      {ts.last_error_message}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

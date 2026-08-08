import type { DashboardBrowseResponse, MissingSummaryTarget } from "../../api/types";
import { formatYmdWithDow } from "../../utils/date";
import { formatPeriodKey } from "./utils";

export function BrowseList({
  year,
  month,
  setYear,
  setMonth,
  data,
  loading,
  error,
  onOpenSummary,
  onShowDayDetail,
  onOpenMissingTarget,
}: {
  year: string;
  month: string;
  setYear: (y: string) => void;
  setMonth: (m: string) => void;
  data: DashboardBrowseResponse | null;
  loading: boolean;
  error: string | null;
  onOpenSummary: (summaryId: string) => void;
  onShowDayDetail: (targetDate: string) => void;
  onOpenMissingTarget: (target: MissingSummaryTarget) => void;
}) {
  return (
    <>
      {/* Filter controls at top of list */}
      <div className="border-b border-slate-200 p-4 flex gap-3">
        <div className="flex-1">
          <label className="block text-[10px] font-bold uppercase text-slate-400">年を選択</label>
          <select
            value={year}
            onChange={(e) => {
              setYear(e.target.value);
              setMonth(""); // Reset month
            }}
            className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {data?.selectable_years.map((y) => (
              <option key={y} value={y}>
                {y}年
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-[10px] font-bold uppercase text-slate-400">月（オプション）</label>
          <select
            value={month}
            onChange={(e) => {
              setMonth(e.target.value);
            }}
            className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">すべての月</option>
            {Array.from({ length: 12 }, (_, i) => {
              const mVal = String(i + 1).padStart(2, "0");
              const optVal = `${year}-${mVal}`;
              return (
                <option key={optVal} value={optVal}>
                  {i + 1}月
                </option>
              );
            })}
          </select>
        </div>
      </div>

      {/* Scrollable list */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
        {loading && <p className="p-4 text-xs text-slate-500">データを読み込み中…</p>}
        {error && <p className="p-4 text-xs text-red-600">{error}</p>}
        {data && (
          <>
            {(data.missing_summary_targets?.length ?? 0) > 0 && (
              <div className="p-4 border-b border-amber-100 bg-amber-50/40">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-amber-700 mb-2">未生成のサマリ ({data.missing_summary_targets?.length ?? 0}件)</h4>
                <div className="space-y-2">
                  {(data.missing_summary_targets ?? []).map((target) => (
                    <button key={`${target.period_type}-${target.period_key}`} onClick={() => onOpenMissingTarget(target)} className="w-full text-left rounded-lg border border-amber-200 bg-white p-3 hover:bg-amber-50 transition-all cursor-pointer">
                      <span className="text-xs font-bold text-amber-800">{target.period_type === "day" ? "日次" : target.period_type === "week" ? "週次" : "月次"}サマリ: {formatPeriodKey(target.period_key, target.period_type)}</span>
                      <p className="mt-1 text-[10px] text-amber-700">{formatYmdWithDow(target.period_start)} ～ {formatYmdWithDow(target.period_end)}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {/* Months summary items (only in Year-level browse) */}
            {data.months.length > 0 && (
              <div className="p-4">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                  月次サマリ ({data.months.length}件)
                </h4>
                <div className="space-y-2">
                  {data.months.map((m) => (
                    <button
                      key={m.summary_id}
                      onClick={() => onOpenSummary(m.summary_id)}
                      className="w-full text-left rounded-lg border border-slate-100 bg-slate-50 p-3 hover:bg-slate-100 transition-all cursor-pointer"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-indigo-600">{formatPeriodKey(m.period_key, "month")}</span>
                        <span className="text-[10px] text-slate-400">{m.period_start ? formatYmdWithDow(m.period_start) : ""} ～ {m.period_end ? formatYmdWithDow(m.period_end) : ""}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-700 font-medium line-clamp-2">{m.summary}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Weeks overlapping */}
            {data.weeks.length > 0 && (
              <div className="p-4">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                  週次サマリ ({data.weeks.length}件)
                </h4>
                <div className="space-y-2">
                  {data.weeks.map((w) => (
                    <button
                      key={w.summary_id}
                      onClick={() => onOpenSummary(w.summary_id)}
                      className="w-full text-left rounded-lg border border-slate-100 bg-slate-50 p-3 hover:bg-slate-100 transition-all cursor-pointer"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-emerald-600">{formatPeriodKey(w.period_key, "week")}</span>
                        <span className="text-[10px] text-slate-400">{w.period_start ? formatYmdWithDow(w.period_start) : ""} ～ {w.period_end ? formatYmdWithDow(w.period_end) : ""}</span>
                      </div>
                      <p className="mt-1 text-xs text-slate-700 font-medium line-clamp-2">{w.summary}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Days list (only in Month-level browse) */}
            {month && (
              <div className="p-4">
                <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                  日別リスト ({data.days.length}件)
                </h4>
                <div className="space-y-2">
                  {data.days.map((d) => (
                    <button
                      key={d.date}
                      onClick={() => {
                        if (d.has_summary && d.summary_id) {
                          onOpenSummary(d.summary_id);
                        } else {
                          onShowDayDetail(d.date);
                        }
                      }}
                      className="w-full text-left rounded-lg border border-slate-100 bg-slate-50 p-3 hover:bg-slate-100 transition-all cursor-pointer"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-800">{formatYmdWithDow(d.date)}</span>
                        <span
                          className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                            d.has_summary
                              ? "bg-blue-50 text-blue-600"
                              : "bg-slate-100 text-slate-500"
                          }`}
                        >
                          {d.has_summary ? "サマリあり" : "サマリ未生成（ログのみ）"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-600 line-clamp-2">
                        {d.summary || "サマリ未生成です。クリックして詳細ログを確認できます。"}
                      </p>
                      {d.topics.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {d.topics.slice(0, 3).map((t) => (
                            <span key={t} className="rounded bg-emerald-50 px-1 py-0.5 text-[9px] text-emerald-700">
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

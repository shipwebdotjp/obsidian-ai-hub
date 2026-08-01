import type { DashboardHomeResponse, SummaryDetail } from "../../api/types";
import { formatYmdWithDow } from "../../utils/date";
import { formatPeriodKey } from "./utils";

export function HomeTab({
  data,
  loading,
  error,
  onGoToSummary,
}: {
  data: DashboardHomeResponse | null;
  loading: boolean;
  error: string | null;
  onGoToSummary: (summary: SummaryDetail) => void;
}) {
  return (
    <div className="h-full overflow-y-auto p-6">
      {loading && <p className="text-sm text-slate-500">ホームデータを読み込み中…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {data && (
        <div className="space-y-6">
          {/* 3 cards grid */}
          <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
            {/* Month summary card */}
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 bg-indigo-50 px-2 py-0.5 rounded-full">
                  今月の月次サマリ
                </span>
                {data.this_month_summary && (
                  <button
                    onClick={() => onGoToSummary(data.this_month_summary!)}
                    className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                  >
                    詳細
                  </button>
                )}
              </div>
              <h3 className="mt-3 text-sm font-bold text-slate-700">
                {data.this_month_summary
                  ? formatPeriodKey(data.this_month_summary.period_key, "month")
                  : "月次未生成"}
              </h3>
              <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                {data.this_month_summary?.summary || "今月のサマリはまだ生成されていません。"}
              </p>
            </div>

            {/* Week summary card */}
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-500 bg-emerald-50 px-2 py-0.5 rounded-full">
                  最新の週次サマリ
                </span>
                {data.latest_week_summary && (
                  <button
                    onClick={() => onGoToSummary(data.latest_week_summary!)}
                    className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                  >
                    詳細
                  </button>
                )}
              </div>
              <h3 className="mt-3 text-sm font-bold text-slate-700">
                {data.latest_week_summary
                  ? formatPeriodKey(data.latest_week_summary.period_key, "week")
                  : "週次未生成"}
              </h3>
              <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                {data.latest_week_summary?.summary || "週次のサマリはまだ生成されていません。"}
              </p>
            </div>

            {/* Yesterday summary card */}
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-amber-500 bg-amber-50 px-2 py-0.5 rounded-full">
                  昨日の日次サマリ
                </span>
                {data.yesterday_summary && (
                  <button
                    onClick={() => onGoToSummary(data.yesterday_summary!)}
                    className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                  >
                    詳細
                  </button>
                )}
              </div>
              <h3 className="mt-3 text-sm font-bold text-slate-700">
                {data.yesterday_summary
                  ? formatYmdWithDow(data.yesterday_summary.period_key)
                  : "昨日未生成"}
              </h3>
              <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                {data.yesterday_summary?.summary || "昨日のサマリはまだ生成されていません。"}
              </p>
            </div>
          </div>

          {/* Today's Activities */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-base font-bold text-slate-800">今日これまでのアクティビティ</h3>

            {/* Times Tracker Row */}
            <div className="mt-4 flex flex-col gap-6 md:flex-row md:items-center justify-between">
              <div className="flex items-center gap-6">
                <div>
                  <span className="text-xs text-slate-400">推定活動カバー時間</span>
                  <div className="text-xl font-bold text-emerald-600">
                    {Math.floor(data.today_activity.active_minutes / 60)}h {Math.round(data.today_activity.active_minutes % 60)}m
                  </div>
                </div>
                <div>
                  <span className="text-xs text-slate-400">非活動時間</span>
                  <div className="text-xl font-bold text-slate-600">
                    {Math.floor(data.today_activity.inactive_minutes / 60)}h {Math.round(data.today_activity.inactive_minutes % 60)}m
                  </div>
                </div>
              </div>
              <div className="flex-1 max-w-md">
                <div className="h-4 w-full rounded-full bg-slate-100 overflow-hidden flex">
                  {data.today_activity.active_minutes + data.today_activity.inactive_minutes > 0 ? (
                    <>
                      <div
                        style={{
                          width: `${(data.today_activity.active_minutes / (data.today_activity.active_minutes + data.today_activity.inactive_minutes)) * 100}%`,
                        }}
                        className="bg-emerald-500 h-full"
                      />
                      <div className="bg-slate-300 h-full flex-1" />
                    </>
                  ) : (
                    <div className="bg-slate-200 w-full h-full" />
                  )}
                </div>
                <span className="mt-1 block text-[10px] text-slate-400 leading-normal">
                  ※活動カバー時間はアプリ変化時等のログから最大30分間を合算・重複排除した参考値です。非活動時間はPCアイドルの実計測値ではありません。
                </span>
              </div>
            </div>

            {/* Logs Table */}
            <div className="mt-6 overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 text-xs font-semibold text-slate-500">
                    <th className="pb-2">時刻</th>
                    <th className="pb-2">アプリ</th>
                    <th className="pb-2">ウィンドウ名</th>
                    <th className="pb-2">要約</th>
                    <th className="pb-2">カテゴリ</th>
                    <th className="pb-2">キーワード</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
                  {data.today_activity.logs.map((log) => (
                    <tr key={log.activity_id} className="hover:bg-slate-50">
                      <td className="py-2.5 pr-2 font-medium text-slate-500">
                        {log.occurred_at.split("T")[1]?.slice(0, 5) || log.occurred_at}
                      </td>
                      <td className="py-2.5 pr-2 truncate max-w-[120px]">{log.app_name}</td>
                      <td className="py-2.5 pr-2 truncate max-w-[200px]" title={log.window_title || ""}>
                        {log.window_title}
                      </td>
                      <td className="py-2.5 pr-2 max-w-[250px] font-medium text-slate-900">{log.summary}</td>
                      <td className="py-2.5 pr-2">
                        <div className="flex flex-col gap-1 items-start">
                          {log.category && (
                            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-medium">
                              {log.category}
                            </span>
                          )}
                          {log.project_name && (
                            <span className="rounded-md bg-sky-50 text-sky-700 border border-sky-100 px-1.5 py-0.5 font-medium flex items-center gap-0.5 whitespace-nowrap">
                              📁 {log.project_name}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {log.keywords.map((k) => (
                            <span key={k} className="rounded bg-slate-100 px-1 text-[10px] text-slate-600">
                              {k}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {data.today_activity.logs.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-slate-400">
                        本日これまでのアクティビティログはありません。
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

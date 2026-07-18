import { useEffect, useState, useCallback, useRef } from "react";
import {
  ApiError,
  getDashboardHome,
  getDashboardBrowse,
  getDashboardSummary,
  getDashboardDayDetails,
  getDashboardStats,
} from "../../api/client";
import type {
  DashboardHomeResponse,
  DashboardBrowseResponse,
  DashboardDayDetailsResponse,
  DashboardStatsResponse,
  SummaryDetail,
  SummaryItem,
  BrowseDayItem,
  StatsBucket,
} from "../../api/types";

// Colors for stats lines
const PALETTE = [
  "#3b82f6", // Blue
  "#10b981", // Emerald
  "#f59e0b", // Amber
  "#ec4899", // Pink
  "#8b5cf6", // Violet
  "#6366f1", // Indigo
  "#ef4444", // Red
  "#14b8a6", // Teal
];

function groupSummaryItemsByKind(items: SummaryItem[]) {
  const groups = new Map<string, SummaryItem[]>();

  for (const item of items) {
    const group = groups.get(item.kind);
    if (group) {
      group.push(item);
    } else {
      groups.set(item.kind, [item]);
    }
  }

  return Array.from(groups, ([kind, items]) => ({ kind, items }));
}

function formatYmdWithDow(ymd: string): string {
  const match = ymd.match(/^\d{4}-\d{2}-\d{2}$/);
  if (!match) return ymd;
  const date = new Date(`${ymd}T00:00:00`);
  const weekdays = ["日", "月", "火", "水", "木", "金", "土"];
  const dow = weekdays[date.getDay()];
  if (dow === undefined) return ymd;
  return ymd.replace(/-/g, "/") + `(${dow})`;
}

function formatPeriodKey(periodKey: string, periodType: "day" | "week" | "month"): string {
  if (periodType === "month") {
    return periodKey.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
  }
  if (periodType === "day") {
    return formatYmdWithDow(periodKey);
  }
  return periodKey;
}

export default function SummaryDashboardPage() {
  const [activeTab, setActiveSubTab] = useState<"home" | "browse" | "stats">("home");

  // --- Home Tab State ---
  const [homeData, setHomeData] = useState<DashboardHomeResponse | null>(null);
  const [homeLoading, setHomeLoading] = useState(false);
  const [homeError, setHomeError] = useState<string | null>(null);

  // --- Browse Tab State ---
  const [browseYear, setBrowseYear] = useState<string>("");
  const [browseMonth, setBrowseMonth] = useState<string>("");
  const [browseData, setBrowseData] = useState<DashboardBrowseResponse | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState<string | null>(null);

  // Detail panel overlay/pane state
  const [selectedSummary, setSelectedSummary] = useState<SummaryDetail | null>(null);
  const [selectedDay, setSelectedDay] = useState<DashboardDayDetailsResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // --- Stats Tab State ---
  const [statsPreset, setStatsPreset] = useState<"year" | "30" | "90" | "custom">("30");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [statsData, setStatsData] = useState<DashboardStatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);

  // Generation counter references to prevent race conditions on fast tab/selection switching
  const homeRequestRef = useRef(0);
  const browseRequestRef = useRef(0);
  const statsRequestRef = useRef(0);
  const detailRequestRef = useRef(0);

  // --- Helper Date Calculations ---
  const getTodayISOString = () => {
    const d = new Date();
    const Y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, "0");
    const D = String(d.getDate()).padStart(2, "0");
    return `${Y}-${M}-${D}`;
  };

  const getSubtractedDateISOString = (days: number) => {
    const d = new Date();
    d.setDate(d.getDate() - days);
    const Y = d.getFullYear();
    const M = String(d.getMonth() + 1).padStart(2, "0");
    const D = String(d.getDate()).padStart(2, "0");
    return `${Y}-${M}-${D}`;
  };

  // --- API Loaders ---
  const loadHome = useCallback(() => {
    const reqId = ++homeRequestRef.current;
    setHomeLoading(true);
    setHomeError(null);
    getDashboardHome()
      .then((data) => {
        if (reqId !== homeRequestRef.current) return;
        setHomeData(data);
      })
      .catch((e) => {
        if (reqId !== homeRequestRef.current) return;
        setHomeError(e instanceof ApiError ? e.message : "ホームデータの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === homeRequestRef.current) setHomeLoading(false);
      });
  }, []);

  const loadBrowse = useCallback((y?: string, m?: string) => {
    const reqId = ++browseRequestRef.current;
    setBrowseLoading(true);
    setBrowseError(null);
    getDashboardBrowse({ year: y || undefined, month: m || undefined })
      .then((data) => {
        if (reqId !== browseRequestRef.current) return;
        setBrowseData(data);
        if (!y && !m) {
          setBrowseYear(data.selected_year);
          setBrowseMonth(data.selected_month || "");
        }
      })
      .catch((e) => {
        if (reqId !== browseRequestRef.current) return;
        setBrowseError(e instanceof ApiError ? e.message : "一覧データの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === browseRequestRef.current) setBrowseLoading(false);
      });
  }, []);

  const loadStats = useCallback((start: string, end: string) => {
    const reqId = ++statsRequestRef.current;
    setStatsLoading(true);
    setStatsError(null);
    getDashboardStats({ start_date: start, end_date: end })
      .then((data) => {
        if (reqId !== statsRequestRef.current) return;
        setStatsData(data);
        setSelectedTopics(data.candidate_topics.slice(0, 5));
        setSelectedKeywords(data.candidate_keywords.slice(0, 5));
      })
      .catch((e) => {
        if (reqId !== statsRequestRef.current) return;
        setStatsError(e instanceof ApiError ? e.message : "統計データの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === statsRequestRef.current) setStatsLoading(false);
      });
  }, []);

  // --- Detail Loader ---
  const showSummaryDetail = (summaryId: string) => {
    const reqId = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setSelectedSummary(null);
    setSelectedDay(null); // Ensure BOTH are not populated at the same time
    getDashboardSummary(summaryId)
      .then((res) => {
        if (reqId !== detailRequestRef.current) return;
        setSelectedSummary(res);
        setSelectedDay(null);
      })
      .catch((e) => {
        if (reqId !== detailRequestRef.current) return;
        setDetailError(e instanceof ApiError ? e.message : "詳細の取得に失敗しました");
      })
      .finally(() => {
        if (reqId === detailRequestRef.current) setDetailLoading(false);
      });
  };

  const showDayDetail = (targetDate: string) => {
    const reqId = ++detailRequestRef.current;
    setDetailLoading(true);
    setDetailError(null);
    setSelectedSummary(null);
    setSelectedDay(null); // Ensure BOTH are not populated at the same time
    getDashboardDayDetails(targetDate)
      .then((res) => {
        if (reqId !== detailRequestRef.current) return;
        setSelectedDay(res);
        setSelectedSummary(null);
      })
      .catch((e) => {
        if (reqId !== detailRequestRef.current) return;
        setDetailError(e instanceof ApiError ? e.message : "日別詳細の取得に失敗しました");
      })
      .finally(() => {
        if (reqId === detailRequestRef.current) setDetailLoading(false);
      });
  };

  // --- Effects ---
  useEffect(() => {
    if (activeTab === "home") {
      loadHome();
    } else if (activeTab === "browse") {
      loadBrowse();
    } else if (activeTab === "stats") {
      // Set default dates
      const end = getTodayISOString();
      const start = getSubtractedDateISOString(29); // 30 days including today
      setStartDate(start);
      setEndDate(end);
      setStatsPreset("30");
      loadStats(start, end);
    }
  }, [activeTab, loadHome, loadBrowse, loadStats]);

  // --- Presets handler ---
  const handlePresetChange = (preset: "year" | "30" | "90" | "custom") => {
    setStatsPreset(preset);
    const end = getTodayISOString();
    let start = "";
    if (preset === "30") {
      start = getSubtractedDateISOString(29);
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    } else if (preset === "90") {
      start = getSubtractedDateISOString(89);
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    } else if (preset === "year") {
      const year = new Date().getFullYear();
      start = `${year}-01-01`;
      setStartDate(start);
      setEndDate(end);
      loadStats(start, end);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      {/* Top Navbar */}
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-bold text-slate-900">サマリダッシュボード</h1>
          <nav className="flex gap-1 rounded-lg bg-slate-100 p-0.5">
            <button
              onClick={() => {
                setActiveSubTab("home");
                setSelectedSummary(null);
                setSelectedDay(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "home"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              ホーム
            </button>
            <button
              onClick={() => {
                setActiveSubTab("browse");
                setSelectedSummary(null);
                setSelectedDay(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "browse"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              一覧
            </button>
            <button
              onClick={() => {
                setActiveSubTab("stats");
                setSelectedSummary(null);
                setSelectedDay(null);
              }}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                activeTab === "stats"
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              } cursor-pointer`}
            >
              統計
            </button>
          </nav>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden">
        {/* HOME TAB */}
        {activeTab === "home" && (
          <div className="h-full overflow-y-auto p-6">
            {homeLoading && <p className="text-sm text-slate-500">ホームデータを読み込み中…</p>}
            {homeError && <p className="text-sm text-red-600">{homeError}</p>}
            {homeData && (
              <div className="space-y-6">
                {/* 3 cards grid */}
                <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
                  {/* Month summary card */}
                  <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-500 bg-indigo-50 px-2 py-0.5 rounded-full">
                        今月の月次サマリ
                      </span>
                      {homeData.this_month_summary && (
                        <button
                          onClick={() => showSummaryDetail(homeData.this_month_summary!.summary_id)}
                          className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                        >
                          詳細
                        </button>
                      )}
                    </div>
                    <h3 className="mt-3 text-sm font-bold text-slate-700">
                      {homeData.this_month_summary
                        ? formatPeriodKey(homeData.this_month_summary.period_key, "month")
                        : "月次未生成"}
                    </h3>
                    <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                      {homeData.this_month_summary?.summary || "今月のサマリはまだ生成されていません。"}
                    </p>
                  </div>

                  {/* Week summary card */}
                  <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-500 bg-emerald-50 px-2 py-0.5 rounded-full">
                        最新の週次サマリ
                      </span>
                      {homeData.latest_week_summary && (
                        <button
                          onClick={() => showSummaryDetail(homeData.latest_week_summary!.summary_id)}
                          className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                        >
                          詳細
                        </button>
                      )}
                    </div>
                    <h3 className="mt-3 text-sm font-bold text-slate-700">
                      {homeData.latest_week_summary
                        ? formatPeriodKey(homeData.latest_week_summary.period_key, "week")
                        : "週次未生成"}
                    </h3>
                    <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                      {homeData.latest_week_summary?.summary || "週次のサマリはまだ生成されていません。"}
                    </p>
                  </div>

                  {/* Yesterday summary card */}
                  <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-amber-500 bg-amber-50 px-2 py-0.5 rounded-full">
                        昨日の日次サマリ
                      </span>
                      {homeData.yesterday_summary && (
                        <button
                          onClick={() => showSummaryDetail(homeData.yesterday_summary!.summary_id)}
                          className="text-xs font-semibold text-blue-600 hover:underline cursor-pointer"
                        >
                          詳細
                        </button>
                      )}
                    </div>
                    <h3 className="mt-3 text-sm font-bold text-slate-700">
                      {homeData.yesterday_summary
                        ? formatYmdWithDow(homeData.yesterday_summary.period_key)
                        : "昨日未生成"}
                    </h3>
                    <p className="mt-2 text-xs text-slate-600 line-clamp-3">
                      {homeData.yesterday_summary?.summary || "昨日のサマリはまだ生成されていません。"}
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
                          {Math.floor(homeData.today_activity.active_minutes / 60)}h {Math.round(homeData.today_activity.active_minutes % 60)}m
                        </div>
                      </div>
                      <div>
                        <span className="text-xs text-slate-400">非活動時間</span>
                        <div className="text-xl font-bold text-slate-600">
                          {Math.floor(homeData.today_activity.inactive_minutes / 60)}h {Math.round(homeData.today_activity.inactive_minutes % 60)}m
                        </div>
                      </div>
                    </div>
                    <div className="flex-1 max-w-md">
                      <div className="h-4 w-full rounded-full bg-slate-100 overflow-hidden flex">
                        {homeData.today_activity.active_minutes + homeData.today_activity.inactive_minutes > 0 ? (
                          <>
                            <div
                              style={{
                                width: `${(homeData.today_activity.active_minutes / (homeData.today_activity.active_minutes + homeData.today_activity.inactive_minutes)) * 100}%`,
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
                        {homeData.today_activity.logs.map((log) => (
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
                              {log.category && (
                                <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-medium">
                                  {log.category}
                                </span>
                              )}
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
                        {homeData.today_activity.logs.length === 0 && (
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
        )}

        {/* BROWSE TAB */}
        {activeTab === "browse" && (
          <div className="flex h-full">
            {/* Left lists column */}
            <div className="w-1/2 flex flex-col border-r border-slate-200 bg-white h-full">
              {/* Filter controls at top of list */}
              <div className="border-b border-slate-200 p-4 flex gap-3">
                <div className="flex-1">
                  <label className="block text-[10px] font-bold uppercase text-slate-400">年を選択</label>
                  <select
                    value={browseYear}
                    onChange={(e) => {
                      setBrowseYear(e.target.value);
                      setBrowseMonth(""); // Reset month
                      loadBrowse(e.target.value, "");
                    }}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    {browseData?.selectable_years.map((y) => (
                      <option key={y} value={y}>
                        {y}年
                      </option>
                    ))}
                  </select>
                </div>
                <div className="flex-1">
                  <label className="block text-[10px] font-bold uppercase text-slate-400">月（オプション）</label>
                  <select
                    value={browseMonth}
                    onChange={(e) => {
                      setBrowseMonth(e.target.value);
                      loadBrowse(browseYear, e.target.value);
                    }}
                    className="mt-1 w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-xs focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="">すべての月</option>
                    {Array.from({ length: 12 }, (_, i) => {
                      const mVal = String(i + 1).padStart(2, "0");
                      const optVal = `${browseYear}-${mVal}`;
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
                {browseLoading && <p className="p-4 text-xs text-slate-500">データを読み込み中…</p>}
                {browseError && <p className="p-4 text-xs text-red-600">{browseError}</p>}
                {browseData && (
                  <>
                    {/* Months summary items (only in Year-level browse) */}
                    {!browseMonth && browseData.months.length > 0 && (
                      <div className="p-4">
                        <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                          月次サマリ ({browseData.months.length}件)
                        </h4>
                        <div className="space-y-2">
                          {browseData.months.map((m) => (
                            <button
                              key={m.summary_id}
                              onClick={() => showSummaryDetail(m.summary_id)}
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
                    {browseData.weeks.length > 0 && (
                      <div className="p-4">
                        <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                          週次サマリ ({browseData.weeks.length}件)
                        </h4>
                        <div className="space-y-2">
                          {browseData.weeks.map((w) => (
                            <button
                              key={w.summary_id}
                              onClick={() => showSummaryDetail(w.summary_id)}
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
                    {browseMonth && (
                      <div className="p-4">
                        <h4 className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                          日別リスト ({browseData.days.length}件)
                        </h4>
                        <div className="space-y-2">
                          {browseData.days.map((d) => (
                            <button
                              key={d.date}
                              onClick={() => {
                                if (d.has_summary && d.summary_id) {
                                  showSummaryDetail(d.summary_id);
                                } else {
                                  showDayDetail(d.date);
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
            </div>

            {/* Right details column */}
            <div className="w-1/2 overflow-y-auto bg-white border-l border-slate-100 h-full p-6">
              {detailLoading && <p className="text-sm text-slate-500">詳細をロード中…</p>}
              {detailError && <p className="text-sm text-red-600">{detailError}</p>}

              {/* 1. Summary Detail view */}
              {selectedSummary && (
                <div className="space-y-5">
                  <div className="flex items-center justify-between">
                    <span className="rounded bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700 uppercase tracking-wider">
                      {selectedSummary.period_type === "day"
                        ? "日次サマリ"
                        : selectedSummary.period_type === "week"
                        ? "週次サマリ"
                        : "月次サマリ"}
                    </span>
                    <span className="text-xs text-slate-500 font-medium">{formatPeriodKey(selectedSummary.period_key, selectedSummary.period_type)}</span>
                  </div>

                  <h2 className="text-lg font-bold text-slate-900">{selectedSummary.summary}</h2>

                  {/* Metadata */}
                  <div className="flex flex-wrap gap-2 text-xs">
                    {selectedSummary.mood && (
                      <span className="rounded bg-blue-50 px-2.5 py-1 text-blue-700 font-medium">
                        気分: {selectedSummary.mood}
                      </span>
                    )}
                    {selectedSummary.sleep_hours !== null && (
                      <span className="rounded bg-indigo-50 px-2.5 py-1 text-indigo-700 font-medium">
                        睡眠: {selectedSummary.sleep_hours}h
                      </span>
                    )}
                  </div>

                  {selectedSummary.topics.length > 0 && (
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">トピック</h3>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {selectedSummary.topics.map((t) => (
                          <span key={t} className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700 font-medium">
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedSummary.projects.length > 0 && (
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">プロジェクト</h3>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {selectedSummary.projects.map((p) => (
                          <span key={p} className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 font-medium">
                            {p}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedSummary.keywords.length > 0 && (
                    <div>
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">キーワード</h3>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {selectedSummary.keywords.map((k) => (
                          <span key={k} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600 font-medium">
                            {k}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Nested item blocks */}
                  <div className="mt-6 space-y-4">
                    {groupSummaryItemsByKind(selectedSummary.items).map(({ kind, items }) => (
                      <section key={kind} className="border-t border-slate-100 pt-3">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">{kind}</h4>
                        <ul className="mt-1 list-disc space-y-2 pl-5">
                          {items.map((item) => (
                            <li
                              key={item.summary_item_id}
                              className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed"
                            >
                              {item.body}
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>

                  {/* If daily summary, we can also load its detailed activity logs directly below it */}
                  {selectedSummary.period_type === "day" && (
                    <button
                      onClick={() => showDayDetail(selectedSummary.period_key)}
                      className="mt-6 w-full text-center rounded-lg border border-blue-200 bg-blue-50 py-2.5 text-xs font-bold text-blue-600 hover:bg-blue-100 transition-all cursor-pointer"
                    >
                      この日の詳細アクティビティログを表示する
                    </button>
                  )}
                </div>
              )}

              {/* 2. Log-only Day Details view */}
              {selectedDay && (
                <div className="space-y-6">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-600 uppercase tracking-wider">
                      日別詳細ログ
                    </span>
                    <span className="text-xs text-slate-500 font-bold">{formatYmdWithDow(selectedDay.date)}</span>
                  </div>

                  {/* Times Tracker Box */}
                  <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
                    <h3 className="text-xs font-bold text-slate-700">活動時間の推定値</h3>
                    <div className="flex items-center gap-6 text-sm">
                      <div>
                        <span className="text-xs text-slate-400">推定活動カバー時間</span>
                        <div className="text-base font-bold text-emerald-600">
                          {Math.floor(selectedDay.active_minutes / 60)}h {Math.round(selectedDay.active_minutes % 60)}m
                        </div>
                      </div>
                      <div>
                        <span className="text-xs text-slate-400">非活動時間</span>
                        <div className="text-base font-bold text-slate-600">
                          {Math.floor(selectedDay.inactive_minutes / 60)}h {Math.round(selectedDay.inactive_minutes % 60)}m
                        </div>
                      </div>
                    </div>
                    <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden flex">
                      <div
                        style={{
                          width: `${(selectedDay.active_minutes / (selectedDay.active_minutes + selectedDay.inactive_minutes)) * 100}%`,
                        }}
                        className="bg-emerald-500 h-full"
                      />
                    </div>
                  </div>

                  {/* Detailed list */}
                  <div className="space-y-4">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">アクティビティタイムライン</h3>
                    <div className="space-y-3">
                      {selectedDay.logs.map((log) => (
                        <div key={log.activity_id} className="rounded-xl border border-slate-100 p-4 hover:shadow-sm transition-all space-y-2">
                          <div className="flex items-center justify-between text-[10px] text-slate-400">
                            <span className="font-bold text-slate-500">{log.occurred_at.split("T")[1]?.slice(0, 5)}</span>
                            <span className="bg-slate-100 px-1.5 py-0.5 rounded text-slate-600 font-medium">{log.app_name}</span>
                          </div>
                          <h4 className="text-sm font-bold text-slate-800">{log.summary}</h4>
                          {log.window_title && (
                            <p className="text-xs text-slate-400 truncate" title={log.window_title}>
                              {log.window_title}
                            </p>
                          )}
                          <div className="flex flex-wrap gap-1">
                            {log.category && (
                              <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] text-indigo-600 font-semibold">
                                {log.category}
                              </span>
                            )}
                            {log.keywords.map((k) => (
                              <span key={k} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                                {k}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {!selectedSummary && !selectedDay && !detailLoading && (
                <div className="flex h-full flex-col items-center justify-center text-slate-400 text-xs">
                  <p>一覧から項目を選択すると、詳細がここに表示されます。</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* STATS TAB */}
        {activeTab === "stats" && (
          <div className="h-full overflow-y-auto p-6 space-y-6">
            {/* Filter control bar */}
            <div className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-slate-500 mr-2">集計期間:</span>
                <button
                  onClick={() => handlePresetChange("30")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    statsPreset === "30" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  } cursor-pointer`}
                >
                  直近30日
                </button>
                <button
                  onClick={() => handlePresetChange("90")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    statsPreset === "90" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  } cursor-pointer`}
                >
                  直近90日
                </button>
                <button
                  onClick={() => handlePresetChange("year")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    statsPreset === "year" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  } cursor-pointer`}
                >
                  今年
                </button>
                <button
                  onClick={() => setStatsPreset("custom")}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                    statsPreset === "custom" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  } cursor-pointer`}
                >
                  期間指定
                </button>
              </div>

              {/* Custom dates input */}
              {statsPreset === "custom" && (
                <div className="flex items-center gap-2 text-xs">
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="rounded-md border border-slate-300 px-2 py-1 focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-slate-400">～</span>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="rounded-md border border-slate-300 px-2 py-1 focus:border-blue-500 focus:outline-none"
                  />
                  <button
                    onClick={() => loadStats(startDate, endDate)}
                    className="rounded-md bg-blue-600 px-3 py-1 font-semibold text-white hover:bg-blue-700 cursor-pointer"
                  >
                    適用
                  </button>
                </div>
              )}
            </div>

            {statsLoading && <p className="text-sm text-slate-500">統計データをロード中…</p>}
            {statsError && <p className="text-sm text-red-600">{statsError}</p>}

            {statsData && (
              <div className="space-y-6">
                {/* 1. Topic & Keyword rate charts */}
                <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                  {/* Topic Trend box */}
                  <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
                    <h3 className="text-sm font-bold text-slate-800">トピック出現率の推移</h3>
                    {/* SVG Line chart */}
                    <SVGLineChart
                      buckets={statsData.buckets}
                      selectedItems={selectedTopics}
                      itemType="topic"
                      colors={PALETTE}
                    />

                    {/* Candidate Selectors */}
                    <div className="border-t border-slate-100 pt-3">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">表示トピックの選択（最大5件）:</span>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {statsData.candidate_topics.map((t) => {
                          const isSel = selectedTopics.includes(t);
                          return (
                            <button
                              key={t}
                              onClick={() => {
                                if (isSel) {
                                  setSelectedTopics(selectedTopics.filter((x) => x !== t));
                                } else if (selectedTopics.length < 5) {
                                  setSelectedTopics([...selectedTopics, t]);
                                }
                              }}
                              className={`rounded px-2 py-1 text-[10px] font-medium transition-all ${
                                isSel
                                  ? "bg-blue-600 text-white"
                                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                              } cursor-pointer`}
                            >
                              {t}
                            </button>
                          );
                        })}
                        {statsData.candidate_topics.length === 0 && (
                          <span className="text-xs text-slate-400">候補となるトピックはありません。</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Keyword Trend box */}
                  <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
                    <h3 className="text-sm font-bold text-slate-800">キーワード出現率の推移</h3>
                    {/* SVG Line chart */}
                    <SVGLineChart
                      buckets={statsData.buckets}
                      selectedItems={selectedKeywords}
                      itemType="keyword"
                      colors={PALETTE}
                    />

                    {/* Candidate Selectors */}
                    <div className="border-t border-slate-100 pt-3">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">表示キーワードの選択（最大5件）:</span>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        {statsData.candidate_keywords.map((k) => {
                          const isSel = selectedKeywords.includes(k);
                          return (
                            <button
                              key={k}
                              onClick={() => {
                                if (isSel) {
                                  setSelectedKeywords(selectedKeywords.filter((x) => x !== k));
                                } else if (selectedKeywords.length < 5) {
                                  setSelectedKeywords([...selectedKeywords, k]);
                                }
                              }}
                              className={`rounded px-2 py-1 text-[10px] font-medium transition-all ${
                                isSel
                                  ? "bg-blue-600 text-white"
                                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                              } cursor-pointer`}
                            >
                              {k}
                            </button>
                          );
                        })}
                        {statsData.candidate_keywords.length === 0 && (
                          <span className="text-xs text-slate-400">候補となるキーワードはありません。</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* 2. Proportional Stacked Bar Chart */}
                <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-slate-800">活動カバー時間と非活動時間の比率</h3>
                    <div className="flex items-center gap-4 text-xs font-semibold">
                      <div className="flex items-center gap-1.5">
                        <span className="h-3 w-3 bg-emerald-500 rounded-sm" />
                        <span className="text-slate-600">活動カバー時間</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="h-3 w-3 bg-slate-100 rounded-sm border border-slate-200" />
                        <span className="text-slate-600">非活動時間</span>
                      </div>
                    </div>
                  </div>

                  <SVGStackedBarChart buckets={statsData.buckets} />

                  <span className="mt-2 block text-[10px] text-slate-400 leading-normal">
                    ※活動カバー時間はアプリ変化時等のログから最大30分間を合算・重複排除した参考値です。非活動時間は実際のPCアイドル状態を示すものではありません。
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Custom SVG Components ---

function SVGLineChart({
  buckets,
  selectedItems,
  itemType,
  colors,
}: {
  buckets: StatsBucket[];
  selectedItems: string[];
  itemType: "topic" | "keyword";
  colors: string[];
}) {
  const width = 800;
  const height = 240;
  const paddingLeft = 45;
  const paddingRight = 130;
  const paddingTop = 20;
  const paddingBottom = 30;

  if (buckets.length === 0 || selectedItems.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        期間を指定するか、項目を選択してください。
      </div>
    );
  }

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;
  const pointsCount = buckets.length;

  const chartTitle = itemType === "topic" ? "トピック出現率の推移" : "キーワード出現率の推移";
  const chartDesc = `選択された${itemType === "topic" ? "トピック" : "キーワード"}の各集計区間における出現率を示す折れ線グラフです。`;

  return (
    <div className="relative overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full min-w-[500px] bg-white"
        role="img"
        aria-label={chartTitle}
      >
        <title>{chartTitle}</title>
        <desc>{chartDesc}</desc>
        {/* Y Grid & Axis Labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((r) => {
          const y = paddingTop + (1 - r) * chartHeight;
          return (
            <g key={r}>
              <line
                x1={paddingLeft}
                y1={y}
                x2={width - paddingRight}
                y2={y}
                stroke="#f1f5f9"
                strokeWidth={1}
                strokeDasharray="4 4"
              />
              <text x={paddingLeft - 8} y={y + 3} textAnchor="end" className="fill-slate-400 text-[9px] font-semibold">
                {Math.round(r * 100)}%
              </text>
            </g>
          );
        })}

        {/* X Axis Labels */}
        {buckets.map((b, idx) => {
          const x = paddingLeft + (idx * chartWidth) / Math.max(1, pointsCount - 1);
          const showLabel = pointsCount <= 12 || idx % Math.ceil(pointsCount / 10) === 0;
          return (
            <g key={b.key}>
              {showLabel && (
                <>
                  <line x1={x} y1={height - paddingBottom} x2={x} y2={height - paddingBottom + 4} stroke="#e2e8f0" />
                  <text x={x} y={height - paddingBottom + 13} textAnchor="middle" className="fill-slate-400 text-[9px] font-semibold">
                    {b.display_label}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {/* Chart Lines */}
        {selectedItems.map((item, itemIdx) => {
          const color = colors[itemIdx % colors.length];
          const linePoints = buckets.map((b, idx) => {
            const x = paddingLeft + (idx * chartWidth) / Math.max(1, pointsCount - 1);
            const total = b.daily_summary_count;
            const count = itemType === "topic" ? (b.topic_counts[item] || 0) : (b.keyword_counts[item] || 0);
            const rate = total > 0 ? count / total : 0;
            const y = paddingTop + (1 - rate) * chartHeight;
            return `${x},${y}`;
          });

          return (
            <g key={item}>
              <polyline fill="none" stroke={color} strokeWidth={2} points={linePoints.join(" ")} />
              {buckets.map((b, idx) => {
                const x = paddingLeft + (idx * chartWidth) / Math.max(1, pointsCount - 1);
                const total = b.daily_summary_count;
                const count = itemType === "topic" ? (b.topic_counts[item] || 0) : (b.keyword_counts[item] || 0);
                const rate = total > 0 ? count / total : 0;
                const y = paddingTop + (1 - rate) * chartHeight;
                return (
                  <circle
                    key={idx}
                    cx={x}
                    cy={y}
                    r={3}
                    className="fill-white"
                    stroke={color}
                    strokeWidth={1.5}
                  />
                );
              })}
            </g>
          );
        })}

        {/* Legend */}
        <g transform={`translate(${width - paddingRight + 12}, ${paddingTop})`}>
          {selectedItems.map((item, itemIdx) => {
            const color = colors[itemIdx % colors.length];
            return (
              <g key={item} transform={`translate(0, ${itemIdx * 18})`}>
                <rect width={10} height={10} fill={color} rx={1.5} />
                <text x={15} y={9} className="fill-slate-600 text-[10px] font-semibold">
                  {item.length > 10 ? `${item.slice(0, 9)}…` : item}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Screen Reader Accessible Data Representation */}
      <div className="sr-only">
        <h4>{chartTitle}のデータ一覧</h4>
        <table>
          <thead>
            <tr>
              <th>集計区間</th>
              {selectedItems.map((item) => (
                <th key={item}>{item}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.key}>
                <td>{b.display_label} ({b.start_date}～{b.end_date})</td>
                {selectedItems.map((item) => {
                  const total = b.daily_summary_count;
                  const count = itemType === "topic" ? (b.topic_counts[item] || 0) : (b.keyword_counts[item] || 0);
                  const rate = total > 0 ? (count / total) * 100 : 0;
                  return (
                    <td key={item}>
                      {Math.round(rate)}% ({count}/{total})
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SVGStackedBarChart({ buckets }: { buckets: StatsBucket[] }) {
  const width = 800;
  const height = 240;
  const paddingLeft = 45;
  const paddingRight = 45;
  const paddingTop = 20;
  const paddingBottom = 30;

  if (buckets.length === 0) {
    return (
      <div className="flex h-[240px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        データがありません。期間を変更してください。
      </div>
    );
  }

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;
  const barCount = buckets.length;
  const rawBarWidth = chartWidth / barCount;
  const barGap = rawBarWidth * 0.25;
  const barWidth = Math.max(2, rawBarWidth - barGap);

  const chartTitle = "活動時間と非活動時間の比率";
  const chartDesc = "各集計区間における、推定活動カバー時間と非活動時間の比率を示す100%積み上げ棒グラフです。";

  return (
    <div className="relative overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full min-w-[500px] bg-white"
        role="img"
        aria-label={chartTitle}
      >
        <title>{chartTitle}</title>
        <desc>{chartDesc}</desc>
        {/* Y Grid & Axis Labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((r) => {
          const y = paddingTop + (1 - r) * chartHeight;
          return (
            <g key={r}>
              <line
                x1={paddingLeft}
                y1={y}
                x2={width - paddingRight}
                y2={y}
                stroke="#f1f5f9"
                strokeWidth={1}
                strokeDasharray="4 4"
              />
              <text x={paddingLeft - 8} y={y + 3} textAnchor="end" className="fill-slate-400 text-[9px] font-semibold">
                {Math.round(r * 100)}%
              </text>
            </g>
          );
        })}

        {/* X Axis Labels */}
        {buckets.map((b, idx) => {
          const x = paddingLeft + idx * rawBarWidth + rawBarWidth / 2;
          const showLabel = barCount <= 12 || idx % Math.ceil(barCount / 10) === 0;
          return (
            <g key={b.key}>
              {showLabel && (
                <>
                  <line x1={x} y1={height - paddingBottom} x2={x} y2={height - paddingBottom + 4} stroke="#e2e8f0" />
                  <text x={x} y={height - paddingBottom + 13} textAnchor="middle" className="fill-slate-400 text-[9px] font-semibold">
                    {b.display_label}
                  </text>
                </>
              )}
            </g>
          );
        })}

        {/* Stacked Bars */}
        {buckets.map((b, idx) => {
          const total = b.active_minutes + b.inactive_minutes;
          const x = paddingLeft + idx * rawBarWidth + barGap / 2;

          if (total === 0) {
            // total is 0: render a neutral grey bar representing "no data"
            return (
              <g key={b.key}>
                <rect
                  x={x}
                  y={paddingTop}
                  width={barWidth}
                  height={chartHeight}
                  fill="#e2e8f0"
                  opacity={0.5}
                  rx={1}
                />
              </g>
            );
          }

          const activeRate = b.active_minutes / total;
          const activeHeight = activeRate * chartHeight;
          const inactiveHeight = (1 - activeRate) * chartHeight;

          const activeY = paddingTop + inactiveHeight;
          const inactiveY = paddingTop;

          return (
            <g key={b.key}>
              {inactiveHeight > 0 && (
                <rect x={x} y={inactiveY} width={barWidth} height={inactiveHeight} className="fill-slate-100" rx={1} />
              )}
              {activeHeight > 0 && (
                <rect x={x} y={activeY} width={barWidth} height={activeHeight} className="fill-emerald-500" rx={1} />
              )}
            </g>
          );
        })}
      </svg>

      {/* Screen Reader Accessible Data Representation */}
      <div className="sr-only">
        <h4>{chartTitle}のデータ一覧</h4>
        <table>
          <thead>
            <tr>
              <th>集計区間</th>
              <th>活動カバー時間</th>
              <th>非活動時間</th>
              <th>活動比率</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => {
              const total = b.active_minutes + b.inactive_minutes;
              const rate = total > 0 ? (b.active_minutes / total) * 100 : 0;
              return (
                <tr key={b.key}>
                  <td>{b.display_label} ({b.start_date}～{b.end_date})</td>
                  <td>{Math.round(b.active_minutes)}分</td>
                  <td>{Math.round(b.inactive_minutes)}分</td>
                  <td>{total > 0 ? `${Math.round(rate)}%` : "データなし"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

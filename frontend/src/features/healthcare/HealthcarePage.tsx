import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getHealthcareOverview } from "../../api/client";
import type { HealthcareOverviewResponse } from "../../api/types";
import { MetricCard } from "./MetricCard";

type Preset = "7" | "30" | "90" | "year" | "custom";

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function subtractDaysISO(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toISODate(d);
}

export default function HealthcarePage() {
  const [preset, setPreset] = useState<Preset>("30");
  const [startDate, setStartDate] = useState(() => subtractDaysISO(29));
  const [endDate, setEndDate] = useState(() => toISODate(new Date()));
  const [data, setData] = useState<HealthcareOverviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestRef = useRef(0);

  const load = useCallback((start: string, end: string) => {
    const reqId = ++requestRef.current;
    setLoading(true);
    setError(null);
    getHealthcareOverview({ start_date: start, end_date: end })
      .then((res) => {
        if (reqId !== requestRef.current) return;
        setData(res);
      })
      .catch((e) => {
        if (reqId !== requestRef.current) return;
        setError(e instanceof ApiError ? e.message : "ヘルスケアデータの取得に失敗しました");
      })
      .finally(() => {
        if (reqId === requestRef.current) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load(startDate, endDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handlePreset = (p: Preset) => {
    setPreset(p);
    if (p === "custom") return;
    let start: string;
    const end = toISODate(new Date());
    if (p === "7") start = subtractDaysISO(6);
    else if (p === "30") start = subtractDaysISO(29);
    else if (p === "90") start = subtractDaysISO(89);
    else {
      // year: Jan 1 to today
      const now = new Date();
      start = `${now.getFullYear()}-01-01`;
    }
    setStartDate(start);
    setEndDate(end);
    load(start, end);
  };

  const handleApplyCustom = () => {
    if (!startDate || !endDate) {
      setError("開始日と終了日を指定してください");
      return;
    }
    if (startDate > endDate) {
      setError("開始日は終了日以前を指定してください");
      return;
    }
    setPreset("custom");
    load(startDate, endDate);
  };

  const hasAnyData = data?.metrics.some((m) => m.buckets.some((b) => b.value !== null)) ?? false;

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-lg font-bold text-slate-900">ヘルスケア</h1>
        <p className="mt-1 text-xs text-slate-500">一定期間の生体指標の推移を概観できます。Quantity 型（歩数・心拍・エネルギーなど）と Category 型（睡眠・スタンド）を日次で集計しています。</p>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Filter bar */}
        <div className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-slate-500 mr-2">集計期間:</span>
            <button
              onClick={() => handlePreset("7")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === "7" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"} cursor-pointer`}
            >
              7日間
            </button>
            <button
              onClick={() => handlePreset("30")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === "30" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"} cursor-pointer`}
            >
              30日間
            </button>
            <button
              onClick={() => handlePreset("90")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === "90" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"} cursor-pointer`}
            >
              90日間
            </button>
            <button
              onClick={() => handlePreset("year")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === "year" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"} cursor-pointer`}
            >
              今年
            </button>
            <button
              onClick={() => setPreset("custom")}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${preset === "custom" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"} cursor-pointer`}
            >
              期間指定
            </button>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1 focus:border-blue-500 focus:outline-none"
              aria-label="開始日"
            />
            <span className="text-slate-400">～</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1 focus:border-blue-500 focus:outline-none"
              aria-label="終了日"
            />
            <button
              onClick={handleApplyCustom}
              className="rounded-md bg-blue-600 px-3 py-1 font-semibold text-white hover:bg-blue-700 cursor-pointer"
            >
              適用
            </button>
          </div>
        </div>

        {loading && <p className="text-sm text-slate-500">ヘルスケアデータをロード中…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}

        {data && !loading && !error && (
          <>
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-500">
                {data.start_date} ～ {data.end_date}
                <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
                  {data.granularity === "day" ? "日別" : data.granularity === "week" ? "週別" : "月別"}
                </span>
              </p>
              {!hasAnyData && (
                <p className="text-xs text-amber-600">
                  この期間のデータがありません。Apple Health の export をインポートすると表示されます。
                </p>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.metrics.map((m) => (
                <MetricCard key={m.key} metric={m} />
              ))}
            </div>

            {!hasAnyData && (
              <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center">
                <p className="text-sm font-semibold text-slate-700">ヘルスケアデータがまだありません</p>
                <p className="mt-1 text-xs text-slate-500">
                  <code className="rounded bg-slate-100 px-1 py-0.5">uv run python -m obsidian_ai_hub.main --import-apple-health --healthcare-export-dir &lt;dir&gt;</code> で取り込んでください。
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

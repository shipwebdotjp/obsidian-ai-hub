import type { DashboardStatsResponse } from "../../api/types";
import { SVGLineChart, SVGStackedBarChart, SVGCategoryHeatmap } from "./charts";
import { PALETTE } from "./utils";

export function StatsTab({
  preset,
  setPreset,
  startDate,
  endDate,
  setStartDate,
  setEndDate,
  data,
  loading,
  error,
  selectedTopics,
  setSelectedTopics,
  selectedKeywords,
  setSelectedKeywords,
  onPresetChange,
  onApplyCustom,
}: {
  preset: "year" | "30" | "90" | "custom";
  setPreset: (p: "year" | "30" | "90" | "custom") => void;
  startDate: string;
  endDate: string;
  setStartDate: (d: string) => void;
  setEndDate: (d: string) => void;
  data: DashboardStatsResponse | null;
  loading: boolean;
  error: string | null;
  selectedTopics: string[];
  setSelectedTopics: (t: string[]) => void;
  selectedKeywords: string[];
  setSelectedKeywords: (k: string[]) => void;
  onPresetChange: (preset: "year" | "30" | "90" | "custom") => void;
  onApplyCustom: (start: string, end: string) => void;
}) {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Filter control bar */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-slate-500 mr-2">集計期間:</span>
          <button
            onClick={() => onPresetChange("30")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              preset === "30" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            } cursor-pointer`}
          >
            直近30日
          </button>
          <button
            onClick={() => onPresetChange("90")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              preset === "90" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            } cursor-pointer`}
          >
            直近90日
          </button>
          <button
            onClick={() => onPresetChange("year")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              preset === "year" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            } cursor-pointer`}
          >
            今年
          </button>
          <button
            onClick={() => setPreset("custom")}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
              preset === "custom" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            } cursor-pointer`}
          >
            期間指定
          </button>
        </div>

        {/* Custom dates input */}
        {preset === "custom" && (
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
              onClick={() => onApplyCustom(startDate, endDate)}
              className="rounded-md bg-blue-600 px-3 py-1 font-semibold text-white hover:bg-blue-700 cursor-pointer"
            >
              適用
            </button>
          </div>
        )}
      </div>

      {loading && <p className="text-sm text-slate-500">統計データをロード中…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {data && (
        <div className="space-y-6">
          {/* 1. Topic & Keyword rate charts */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Topic Trend box */}
            <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
              <h3 className="text-sm font-bold text-slate-800">トピック出現率の推移</h3>
              {/* SVG Line chart */}
              <SVGLineChart
                buckets={data.buckets}
                selectedItems={selectedTopics}
                itemType="topic"
                colors={PALETTE}
              />

              {/* Candidate Selectors */}
              <div className="border-t border-slate-100 pt-3">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">表示トピックの選択（最大5件）:</span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {data.candidate_topics.map((t) => {
                    const isSel = selectedTopics.includes(t);
                    const selIdx = selectedTopics.indexOf(t);
                    const paletteColor = isSel ? PALETTE[selIdx % PALETTE.length] : undefined;
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
                        style={isSel && paletteColor ? { backgroundColor: paletteColor, color: "#fff" } : undefined}
                        className={`rounded px-2 py-1 text-[10px] font-medium transition-all ${
                          isSel
                            ? ""
                            : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        } cursor-pointer`}
                      >
                        {t}
                      </button>
                    );
                  })}
                  {data.candidate_topics.length === 0 && (
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
                buckets={data.buckets}
                selectedItems={selectedKeywords}
                itemType="keyword"
                colors={PALETTE}
              />

              {/* Candidate Selectors */}
              <div className="border-t border-slate-100 pt-3">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">表示キーワードの選択（最大5件）:</span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {data.candidate_keywords.map((k) => {
                    const isSel = selectedKeywords.includes(k);
                    const selIdx = selectedKeywords.indexOf(k);
                    const paletteColor = isSel ? PALETTE[selIdx % PALETTE.length] : undefined;
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
                        style={isSel && paletteColor ? { backgroundColor: paletteColor, color: "#fff" } : undefined}
                        className={`rounded px-2 py-1 text-[10px] font-medium transition-all ${
                          isSel
                            ? ""
                            : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        } cursor-pointer`}
                      >
                        {k}
                      </button>
                    );
                  })}
                  {data.candidate_keywords.length === 0 && (
                    <span className="text-xs text-slate-400">候補となるキーワードはありません。</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 2. Hourly Category Heatmap */}
          <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm space-y-4">
            <h3 className="text-sm font-bold text-slate-800">時間帯 × カテゴリー ヒートマップ</h3>
            <SVGCategoryHeatmap buckets={data.hourly_category_buckets} categories={data.activity_categories} />
            <span className="mt-2 block text-[10px] text-slate-400 leading-normal">
              ※各時間帯における活動ログのカテゴリ構成比（%）です。セル内の数値は割合、括弧内は件数です。
            </span>
          </div>

          {/* 3. Proportional Stacked Bar Chart */}
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

            <SVGStackedBarChart buckets={data.buckets} />

            <span className="mt-2 block text-[10px] text-slate-400 leading-normal">
              ※活動カバー時間はアプリ変化時等のログから最大30分間を合算・重複排除した参考値です。非活動時間は実際のPCアイドル状態を示すものではありません。
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

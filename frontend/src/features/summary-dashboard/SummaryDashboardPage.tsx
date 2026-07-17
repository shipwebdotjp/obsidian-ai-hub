import { useCallback, useEffect, useState } from "react";
import SummaryDashboardList from "./SummaryDashboardList";
import SummaryDashboardDetail from "./SummaryDashboardDetail";
import type {
  SummaryListItem,
  SummaryOptionsResponse,
  SummaryPeriodType,
} from "../../api/types";
import { ApiError, getSummaryOptions } from "../../api/client";

export default function SummaryDashboardPage() {
  const [periodType, setPeriodType] = useState<SummaryPeriodType | "">("");
  const [period, setPeriod] = useState("");
  const [topic, setTopic] = useState("");
  const [project, setProject] = useState("");
  const [person, setPerson] = useState("");
  const [selected, setSelected] = useState<SummaryListItem | null>(null);
  const [options, setOptions] = useState<SummaryOptionsResponse | null>(null);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const reload = useCallback(() => setRefreshKey((v) => v + 1), []);

  useEffect(() => {
    getSummaryOptions()
      .then(setOptions)
      .catch((e) => {
        const msg = e instanceof ApiError ? e.message : "フィルタ取得に失敗しました";
        setOptionsError(msg);
      });
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-slate-200 bg-white p-3">
        <h1 className="text-base font-semibold">サマリダッシュボード</h1>
        <select
          value={periodType}
          onChange={(e) => {
            setPeriodType(e.target.value as SummaryPeriodType | "");
            setSelected(null);
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべての種別</option>
          <option value="day">日次</option>
          <option value="week">週次</option>
          <option value="month">月次</option>
        </select>
        <input
          type="search"
          value={period}
          onChange={(e) => {
            setPeriod(e.target.value);
            setSelected(null);
          }}
          placeholder="期間 (例: 2026-07-13)"
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <select
          value={topic}
          onChange={(e) => {
            setTopic(e.target.value);
            setSelected(null);
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべてのトピック</option>
          {options?.topics.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            setSelected(null);
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべてのプロジェクト</option>
          {options?.projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          value={person}
          onChange={(e) => {
            setPerson(e.target.value);
            setSelected(null);
          }}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">すべての人物</option>
          {options?.people.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => {
            setPeriodType("");
            setPeriod("");
            setTopic("");
            setProject("");
            setPerson("");
            setSelected(null);
            reload();
          }}
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          クリア
        </button>
        <button
          type="button"
          onClick={reload}
          className="rounded border border-slate-300 px-3 py-1 text-sm"
        >
          再読み込み
        </button>
        {optionsError && (
          <span className="text-xs text-red-600">{optionsError}</span>
        )}
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-1/2 border-r border-slate-200">
          <SummaryDashboardList
            periodType={periodType}
            period={period}
            topic={topic}
            project={project}
            person={person}
            onSelect={setSelected}
            refreshKey={refreshKey}
          />
        </div>
        <div className="w-1/2 overflow-hidden">
          {selected ? (
            <SummaryDashboardDetail summaryId={selected.summary_id} />
          ) : (
            <p className="p-6 text-sm text-slate-500">
              左の一覧からサマリを選択してください。
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

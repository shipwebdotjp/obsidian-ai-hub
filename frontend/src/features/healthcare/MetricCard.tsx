import type { HealthcareMetricSeries } from "../../api/types";
import { HealthcareTrendChart } from "./charts";

const PALETTE: Record<string, string> = {
  steps: "#3b82f6",
  heart_rate: "#ef4444",
  resting_heart_rate: "#f97316",
  hrv: "#8b5cf6",
  active_energy: "#f59e0b",
  basal_energy: "#eab308",
  distance: "#10b981",
  flights: "#6366f1",
  exercise_time: "#14b8a6",
  sleep: "#0ea5e9",
  stand_hours: "#84cc16",
};

export function formatMetricValue(value: number | null, key: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  switch (key) {
    case "steps":
    case "flights":
    case "exercise_time":
      return Math.round(value).toLocaleString("ja-JP");
    case "distance":
      return value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
    case "heart_rate":
    case "resting_heart_rate":
    case "hrv":
    case "active_energy":
    case "basal_energy":
    case "sleep":
    case "stand_hours":
      return value.toFixed(1);
    default:
      return value.toLocaleString("ja-JP", { maximumFractionDigits: 1 });
  }
}

export function MetricCard({ metric }: { metric: HealthcareMetricSeries }) {
  const color = PALETTE[metric.key] ?? "#3b82f6";
  const hasData = metric.buckets.some((b) => b.value !== null);
  const latestLabel = hasData ? formatMetricValue(metric.latest_value, metric.key) : "—";
  const delta = metric.delta_pct;
  const showDelta = delta !== null && delta !== undefined && hasData && metric.previous_value !== null;
  // Derive trend once to avoid nested ternaries and repeated non-null assertions.
  let trend: "up" | "down" | "flat" = "flat";
  let trendClass = "text-slate-500";
  let trendSymbol = "—";
  let deltaText = "";
  if (showDelta) {
    const d = delta as number;
    if (d > 0) trend = "up";
    else if (d < 0) trend = "down";
    trendClass = { up: "text-emerald-600", down: "text-rose-600", flat: "text-slate-500" }[trend];
    trendSymbol = { up: "▲", down: "▼", flat: "—" }[trend];
    deltaText = `${d > 0 ? "+" : ""}${d.toFixed(1)}%`;
  }

  return (
    <div className="flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-800">{metric.label}</h3>
          <span className="mt-0.5 inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">{metric.unit}</span>
        </div>
        <div className="text-right">
          <div className="text-lg font-bold text-slate-900 leading-none" data-testid={`healthcare-latest-${metric.key}`}>
            {latestLabel}
            <span className="ml-1 text-[10px] font-medium text-slate-500">{latestLabel !== "—" ? metric.unit : ""}</span>
          </div>
          {showDelta ? (
            <div className={`mt-1 text-[11px] font-semibold ${trendClass}`} data-testid={`healthcare-delta-${metric.key}`}>
              {trendSymbol} {deltaText}
              <span className="ml-1 text-[10px] font-normal text-slate-400">前回比</span>
            </div>
          ) : (
            <div className="mt-1 text-[11px] text-slate-400">—</div>
          )}
        </div>
      </div>

      <div className="mt-3">
        <HealthcareTrendChart buckets={metric.buckets} color={color} unit={metric.unit} label={metric.label} />
      </div>

      {hasData && (
        <div className="mt-2 flex gap-3 text-[10px] text-slate-500">
          {metric.buckets.length > 0 && (
            <>
              <span>
                件数: {metric.buckets.filter((b) => b.count > 0).length}/{metric.buckets.length}区間
              </span>
              <span className="ml-auto opacity-60">{metric.aggregation === "sum" ? "合計" : "平均"}で集計</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

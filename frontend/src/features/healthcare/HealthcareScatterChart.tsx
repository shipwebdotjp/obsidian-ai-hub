import type { HealthcareCorrelationResponse } from "../../api/types";

interface HealthcareScatterChartProps {
  data: HealthcareCorrelationResponse;
}

function correlationStrengthLabel(r: number | null): string {
  if (r === null || r === undefined) return "—";
  const a = Math.abs(r);
  if (a >= 0.7) return r > 0 ? "強い正の相関" : "強い負の相関";
  if (a >= 0.4) return r > 0 ? "中程度の正の相関" : "中程度の負の相関";
  if (a >= 0.2) return r > 0 ? "弱い正の相関" : "弱い負の相関";
  return "ほぼ無相関";
}

export function HealthcareScatterChart({ data }: HealthcareScatterChartProps) {
  const { points, pearson_r, regression_slope, regression_intercept, x_label, y_label, x_unit, y_unit } = data;

  const width = 520;
  const height = 420;
  const paddingLeft = 48;
  const paddingRight = 18;
  const paddingTop = 18;
  const paddingBottom = 38;

  if (points.length === 0) {
    return (
      <div className="flex h-[320px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        この期間・組み合わせでは両方の指標が揃った日がありません。
      </div>
    );
  }

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);

  const xRange = xMax - xMin;
  const yRange = yMax - yMin;
  const xPad = xRange === 0 ? Math.abs(xMin) * 0.05 || 1 : xRange * 0.12;
  const yPad = yRange === 0 ? Math.abs(yMin) * 0.05 || 1 : yRange * 0.12;
  let xLo = xMin - xPad;
  let xHi = xMax + xPad;
  let yLo = yMin - yPad;
  let yHi = yMax + yPad;
  if (xLo < 0 && xMin >= 0) xLo = 0;
  if (yLo < 0 && yMin >= 0) yLo = 0;
  const xSpan = xHi - xLo || 1;
  const ySpan = yHi - yLo || 1;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const sx = (x: number) => paddingLeft + ((x - xLo) / xSpan) * chartWidth;
  const sy = (y: number) => paddingTop + ((yHi - y) / ySpan) * chartHeight;

  // Regression line endpoints (clamped to x domain); also clip y to plot area
  // and store slope/intercept on the object to avoid non-null assertions later.
  let regLine: { x1: number; y1: number; x2: number; y2: number; slope: number; intercept: number } | null = null;
  if (regression_slope !== null && regression_slope !== undefined && regression_intercept !== null && regression_intercept !== undefined) {
    const y1 = regression_slope * xLo + regression_intercept;
    const y2 = regression_slope * xHi + regression_intercept;
    regLine = { x1: sx(xLo), y1: sy(y1), x2: sx(xHi), y2: sy(y2), slope: regression_slope, intercept: regression_intercept };
  }
  const plotClipId = `scatter-plot-clip-${x_label}-${y_label}`.replace(/[^a-zA-Z0-9_-]/g, "_");

  const rLabel = pearson_r !== null && pearson_r !== undefined ? pearson_r.toFixed(2) : "—";
  const strength = correlationStrengthLabel(pearson_r);

  const xTicks = [xLo, (xLo + xHi) / 2, xHi];
  const yTicks = [yLo, (yLo + yHi) / 2, yHi];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded bg-slate-900 px-2 py-1 font-semibold text-white">r = {rLabel}</span>
        <span className="text-slate-600">{strength}</span>
        <span className="text-slate-400">n = {data.n}</span>
        {regLine && (
          <span className="text-slate-500">
            回帰: y = {regLine.slope.toFixed(3)}·x + {regLine.intercept.toFixed(2)}
          </span>
        )}
      </div>

      <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-white">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label={`${x_label}と${y_label}の相関散布図`}>
          <title>{`${x_label}（${x_unit}）と ${y_label}（${y_unit}）の相関`}</title>
          <defs>
            <clipPath id={plotClipId}>
              <rect x={paddingLeft} y={paddingTop} width={chartWidth} height={chartHeight} />
            </clipPath>
          </defs>
          {/* Grid */}
          {xTicks.map((v) => {
            const x = sx(v);
            return <line key={`x-${v}`} x1={x} y1={paddingTop} x2={x} y2={height - paddingBottom} stroke="#f1f5f9" strokeDasharray="4 4" />;
          })}
          {yTicks.map((v) => {
            const y = sy(v);
            return <line key={`y-${v}`} x1={paddingLeft} y1={y} x2={width - paddingRight} y2={y} stroke="#f1f5f9" strokeDasharray="4 4" />;
          })}

          <g clipPath={`url(#${plotClipId})`}>
            {/* Regression line */}
            {regLine && <line x1={regLine.x1} y1={regLine.y1} x2={regLine.x2} y2={regLine.y2} stroke="#3b82f6" strokeWidth={1.5} strokeDasharray="6 4" opacity={0.9} />}

            {/* Points */}
            {points.map((p) => (
              <g key={p.date}>
                <circle cx={sx(p.x)} cy={sy(p.y)} r={4} fill="#3b82f6" stroke="white" strokeWidth={1.2} opacity={0.85}>
                  <title>{`${p.date}: ${x_label} ${p.x} ${x_unit}, ${y_label} ${p.y} ${y_unit}`}</title>
                </circle>
              </g>
            ))}
          </g>

          {/* X axis ticks/labels */}
          {xTicks.map((v) => {
            const x = sx(v);
            return (
              <g key={`x-tick-${v}`}>
                <line x1={x} y1={height - paddingBottom} x2={x} y2={height - paddingBottom + 4} stroke="#e2e8f0" />
                <text x={x} y={height - paddingBottom + 14} textAnchor="middle" className="fill-slate-500 text-[8px] font-semibold">
                  {formatAxisTick(v, x_unit)}
                </text>
              </g>
            );
          })}
          {yTicks.map((v) => {
            const y = sy(v);
            return (
              <g key={`y-tick-${v}`}>
                <line x1={paddingLeft - 4} y1={y} x2={paddingLeft} y2={y} stroke="#e2e8f0" />
                <text x={paddingLeft - 6} y={y + 3} textAnchor="end" className="fill-slate-500 text-[8px] font-semibold">
                  {formatAxisTick(v, y_unit)}
                </text>
              </g>
            );
          })}

          {/* Axis titles */}
          <text x={paddingLeft + chartWidth / 2} y={height - 2} textAnchor="middle" className="fill-slate-700 text-[9px] font-bold">
            {x_label} ({x_unit})
          </text>
          <text transform={`rotate(-90 ${12} ${paddingTop + chartHeight / 2})`} x={12} y={paddingTop + chartHeight / 2} textAnchor="middle" className="fill-slate-700 text-[9px] font-bold">
            {y_label} ({y_unit})
          </text>
        </svg>

        <div className="sr-only">
          <table>
            <thead>
              <tr>
                <th>日付</th>
                <th>{x_label}</th>
                <th>{y_label}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.date}>
                  <td>{p.date}</td>
                  <td>{p.x}</td>
                  <td>{p.y}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-[11px] text-slate-400">日次で両指標が揃った日のみをプロットしています。週・月集計では推移タブを、散布図では常に日次で相関を評価します。</p>
    </div>
  );
}

function formatAxisTick(v: number, unit: string): string {
  if (unit === "km") return v.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  if (unit === "count" || unit === "min") {
    return Math.abs(v - Math.round(v)) < 0.01 ? Math.round(v).toLocaleString("ja-JP") : v.toFixed(1);
  }
  return v.toFixed(1);
}

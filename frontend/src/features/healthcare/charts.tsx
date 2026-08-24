import type { HealthcareBucket } from "../../api/types";

interface HealthcareTrendChartProps {
  buckets: HealthcareBucket[];
  color: string;
  unit?: string;
  label?: string;
}

export function HealthcareTrendChart({ buckets, color, unit, label }: HealthcareTrendChartProps) {
  const width = 400;
  const height = 140;
  const paddingLeft = 38;
  const paddingRight = 12;
  const paddingTop = 14;
  const paddingBottom = 22;

  const values = buckets.map((b) => b.value).filter((v): v is number => v !== null && Number.isFinite(v));

  if (buckets.length === 0) {
    return (
      <div className="flex h-[140px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        データがありません。
      </div>
    );
  }

  if (values.length === 0) {
    return (
      <div className="flex h-[140px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        この期間のデータがありません。
      </div>
    );
  }

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal;
  const pad = range === 0 ? Math.abs(minVal) * 0.05 || 1 : range * 0.12;
  let yMin = minVal - pad;
  let yMax = maxVal + pad;
  if (yMin < 0 && minVal >= 0) yMin = 0;

  const yRange = yMax - yMin || 1;

  const getX = (idx: number) => {
    if (buckets.length === 1) return paddingLeft + chartWidth / 2;
    return paddingLeft + (idx * chartWidth) / (buckets.length - 1);
  };
  const getY = (value: number) => paddingTop + ((yMax - value) / yRange) * chartHeight;

  // Build segments that skip nulls
  const segments: Array<Array<{ x: number; y: number }>> = [];
  let current: Array<{ x: number; y: number }> = [];
  buckets.forEach((b, idx) => {
    if (b.value !== null && Number.isFinite(b.value)) {
      current.push({ x: getX(idx), y: getY(b.value) });
    } else {
      if (current.length > 0) {
        segments.push(current);
        current = [];
      }
    }
  });
  if (current.length > 0) segments.push(current);

  const chartTitle = label ? `${label}の推移` : "推移グラフ";
  // For count/min, a small range can make rounded ticks collide (e.g., 10.2/10.5/10.8 -> "10"/"11"/"11").
  // Keep one decimal when the range is narrow to keep labels distinct.
  const yTickRange = yMax - yMin;
  const useDecimalForCount = (unit === "count" || unit === "min") && yTickRange < 10;
  const yTicks = [
    { value: yMax, label: formatTick(yMax, unit, useDecimalForCount) },
    { value: (yMax + yMin) / 2, label: formatTick((yMax + yMin) / 2, unit, useDecimalForCount) },
    { value: yMin, label: formatTick(yMin, unit, useDecimalForCount) },
  ];

  return (
    <div className="relative overflow-hidden">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full bg-white"
        role="img"
        aria-label={chartTitle}
      >
        <title>{chartTitle}</title>
        {/* Y grid & labels */}
        {yTicks.map((t) => {
          const y = getY(t.value);
          return (
            <g key={t.label + String(t.value)}>
              <line
                x1={paddingLeft}
                y1={y}
                x2={width - paddingRight}
                y2={y}
                stroke="#f1f5f9"
                strokeWidth={1}
                strokeDasharray="4 4"
              />
              <text x={paddingLeft - 6} y={y + 3} textAnchor="end" className="fill-slate-400 text-[8px] font-semibold">
                {t.label}
              </text>
            </g>
          );
        })}

        {/* X axis labels */}
        {buckets.map((b, idx) => {
          const showLabel = buckets.length <= 8 || idx % Math.ceil(buckets.length / 8) === 0;
          if (!showLabel) return null;
          const x = getX(idx);
          return (
            <g key={b.key}>
              <line x1={x} y1={height - paddingBottom} x2={x} y2={height - paddingBottom + 3} stroke="#e2e8f0" />
              <text x={x} y={height - paddingBottom + 12} textAnchor="middle" className="fill-slate-400 text-[7px] font-semibold">
                {b.display_label}
              </text>
            </g>
          );
        })}

        {/* Line segments */}
        {segments.map((seg, si) => {
          if (seg.length === 1) {
            // Single point: just a dot
            const p = seg[0]!;
            return <circle key={si} cx={p.x} cy={p.y} r={3.5} fill={color} stroke="white" strokeWidth={1.5} />;
          }
          const points = seg.map((p) => `${p.x},${p.y}`).join(" ");
          return (
            <g key={si}>
              <polyline fill="none" stroke={color} strokeWidth={2} points={points} strokeLinejoin="round" strokeLinecap="round" />
              {seg.map((p, pi) => (
                <circle key={pi} cx={p.x} cy={p.y} r={2.8} className="fill-white" stroke={color} strokeWidth={1.5} />
              ))}
            </g>
          );
        })}
      </svg>

      <div className="sr-only">
        <table>
          <thead>
            <tr>
              <th>日付</th>
              <th>値</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.key}>
                <td>
                  {b.display_label} ({b.start_date}～{b.end_date})
                </td>
                <td>{b.value !== null ? `${b.value} ${unit ?? ""}` : "データなし"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatTick(v: number, unit?: string, useDecimalForCount?: boolean): string {
  // Keep ticks compact: 1 decimal for most, 0 for counts, 2 for km.
  // For count/min with a narrow range, keep one decimal to avoid label collisions.
  let s: string;
  if (unit === "km") {
    s = v.toFixed(2);
  } else if (unit === "count" || unit === "min") {
    s = useDecimalForCount ? v.toFixed(1) : Math.round(v).toLocaleString("ja-JP");
  } else {
    s = v.toFixed(1);
  }
  // Trim unnecessary trailing zeros for km case but keep compact
  if (unit === "km") {
    s = s.replace(/0+$/, "").replace(/\.$/, "");
    if (s === "") s = "0";
  }
  return s;
}

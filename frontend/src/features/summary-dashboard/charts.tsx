import type { StatsBucket, HourlyCategoryBucket } from "../../api/types";

// --- Custom SVG Components ---

export function SVGLineChart({
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

export function SVGStackedBarChart({ buckets }: { buckets: StatsBucket[] }) {
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

export function SVGCategoryHeatmap({
  buckets,
  categories,
}: {
  buckets: HourlyCategoryBucket[];
  categories: string[];
}) {
  const cellWidth = 52;
  const labelWidth = 90;
  const rowHeight = 28;

  if (!buckets || buckets.length === 0 || categories.length === 0) {
    return (
      <div className="flex h-[200px] items-center justify-center bg-slate-50 text-xs text-slate-400 rounded-lg">
        データがありません。期間を変更してください。
      </div>
    );
  }

  const getOpacity = (ratio: number): string => {
    if (ratio === 0) return "rgba(59, 130, 246, 0)";
    return `rgba(59, 130, 246, ${0.07 + ratio * 0.93})`;
  };

  return (
    <div className="relative overflow-x-auto">
      <div className="min-w-[500px]">
        <table
          className="w-full border-collapse text-[10px]"
          role="img"
          aria-label="時間帯 × カテゴリー ヒートマップ"
        >
          <caption className="sr-only">
            各時間帯における活動ログのカテゴリ構成比を示すヒートマップです。
          </caption>
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-white p-1 text-left text-slate-500 font-semibold" style={{ minWidth: labelWidth }} />
              {buckets.map((b) => (
                <th
                  key={b.hour}
                  className="p-1 text-center text-slate-500 font-semibold"
                  style={{ width: cellWidth }}
                >
                  {b.hour}時
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <tr key={cat}>
                <td
                  className="sticky left-0 z-10 bg-white p-1 font-semibold text-slate-600 truncate"
                  style={{ maxWidth: labelWidth }}
                  title={cat}
                >
                  {cat}
                </td>
                {buckets.map((b) => {
                  const count = b.category_counts[cat] || 0;
                  const total = b.total_log_count;
                  const ratio = total > 0 ? count / total : 0;
                  const pct = Math.round(ratio * 100);
                  const tooltip = `${cat} / ${b.hour}時 / ${pct}% (${count}/${total})`;

                  if (total === 0) {
                    return (
                      <td
                        key={b.hour}
                        className="p-0 text-center text-slate-300"
                        style={{ width: cellWidth, height: rowHeight }}
                        title={`${cat} / ${b.hour}時 / データなし`}
                      >
                        <span className="sr-only">データなし</span>
                        -
                      </td>
                    );
                  }

                  return (
                    <td
                      key={b.hour}
                      className="p-0 text-center align-middle"
                      style={{
                        width: cellWidth,
                        height: rowHeight,
                        backgroundColor: getOpacity(ratio),
                        color: ratio > 0.55 ? "#fff" : "#475569",
                      }}
                      title={tooltip}
                    >
                      <span className="sr-only">{tooltip}</span>
                      {pct}%&nbsp;
                      <span className="text-[8px] opacity-70">({count})</span>
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

# summary-dashboard-ux-fixes

## 2026-07-18 Date formatting
- Added module-scope helpers `formatYmdWithDow` and `formatPeriodKey` to `SummaryDashboardPage.tsx`.
- Applied formatting to all displayed dates: home cards, browse month/week/day lists, period ranges, and detail panel headers.
- Kept week `period_key` (`YYYY-Www`) unchanged; left stats tab, SVG chart labels, `sr-only` table, and activity log timestamps untouched.
- `npx tsc --noEmit` passes. Grep audit confirms no raw `{m.period_key}`, `{w.period_key}`, `{d.date}`, `{selectedDay.date}`, or `{selectedSummary.period_key}` remain as rendered values (only `key={d.date}` React key).

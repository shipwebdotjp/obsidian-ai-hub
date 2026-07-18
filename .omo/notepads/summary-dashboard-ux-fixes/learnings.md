# summary-dashboard-ux-fixes

## 2026-07-18 Date formatting
- Added module-scope helpers `formatYmdWithDow` and `formatPeriodKey` to `SummaryDashboardPage.tsx`.
- Applied formatting to all displayed dates: home cards, browse month/week/day lists, period ranges, and detail panel headers.
- Kept week `period_key` (`YYYY-Www`) unchanged; left stats tab, SVG chart labels, `sr-only` table, and activity log timestamps untouched.
- `npx tsc --noEmit` passes. Grep audit confirms no raw `{m.period_key}`, `{w.period_key}`, `{d.date}`, `{selectedDay.date}`, or `{selectedSummary.period_key}` remain as rendered values (only `key={d.date}` React key).

## 2026-07-18 Pointer cursor on buttons
- Added `cursor-pointer` to every `<button>` in `SummaryDashboardPage.tsx` (17 buttons total): tab nav, home card 「詳細」, browse month/week/day list rows, stats preset selectors, custom-date apply, topic/keyword candidate pills, and summary detail activity-log button.
- Verified with `npx tsc --noEmit` and `grep -c` equality: `<button` count == `cursor-pointer` count == 17.

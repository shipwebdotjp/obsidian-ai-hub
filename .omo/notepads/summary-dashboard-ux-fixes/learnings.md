# summary-dashboard-ux-fixes

## 2026-07-18 Date formatting
- Added module-scope helpers `formatYmdWithDow` and `formatPeriodKey` to `SummaryDashboardPage.tsx`.
- Applied formatting to all displayed dates: home cards, browse month/week/day lists, period ranges, and detail panel headers.
- Kept week `period_key` (`YYYY-Www`) unchanged; left stats tab, SVG chart labels, `sr-only` table, and activity log timestamps untouched.
- `npx tsc --noEmit` passes. Grep audit confirms no raw `{m.period_key}`, `{w.period_key}`, `{d.date}`, `{selectedDay.date}`, or `{selectedSummary.period_key}` remain as rendered values (only `key={d.date}` React key).

## 2026-07-18 Pointer cursor on buttons
- Added `cursor-pointer` to every `<button>` in `SummaryDashboardPage.tsx` (17 buttons total): tab nav, home card 「詳細」, browse month/week/day list rows, stats preset selectors, custom-date apply, topic/keyword candidate pills, and summary detail activity-log button.
- Verified with `npx tsc --noEmit` and `grep -c` equality: `<button` count == `cursor-pointer` count == 17.

## 2026-07-18 Browse defaults and home-to-browse detail jump
- Defaulted `browseYear` and `browseMonth` to the current year/month on initial state so the browse tab opens on the current period.
- Wired the browse `useEffect` to fetch with the current `browseYear`/`browseMonth` and added `skipNextBrowseLoadRef` to suppress the effect when manually driving a cross-tab load from a home card.
- Removed explicit `loadBrowse` calls from the year/month `<select>` onChange handlers to prevent double-fetching.
- Removed the `!browseMonth &&` guard so the monthly summary section renders whenever the backend returns months.
- Added `goToBrowseForSummary(summary)` and wired it to the three home card 「詳細」 buttons; it sets the filters to the summary's period, switches to the browse tab, and shows the summary detail in the right pane without auto-loading day logs.
- Verified with `npx tsc --noEmit` (exit 0) and grep audits: `loadBrowse(` only appears inside the helper/effect, `goToBrowseForSummary` is used for all three home cards, and the months guard no longer requires `!browseMonth`.

import type { SummaryItem } from "../../api/types";
import { formatYmdWithDow } from "../../utils/date";

// Colors for stats lines
export const PALETTE = [
  "#3b82f6", // Blue
  "#10b981", // Emerald
  "#f59e0b", // Amber
  "#ec4899", // Pink
  "#8b5cf6", // Violet
  "#6366f1", // Indigo
  "#ef4444", // Red
  "#14b8a6", // Teal
];

export function groupSummaryItemsByKind(items: SummaryItem[]) {
  const groups = new Map<string, SummaryItem[]>();

  for (const item of items) {
    const group = groups.get(item.kind);
    if (group) {
      group.push(item);
    } else {
      groups.set(item.kind, [item]);
    }
  }

  return Array.from(groups, ([kind, items]) => ({ kind, items }));
}

export function formatPeriodKey(periodKey: string, periodType: "day" | "week" | "month"): string {
  if (periodType === "month") {
    return periodKey.replace(/^(\d{4})-(\d{2})$/, "$1/$2");
  }
  if (periodType === "day") {
    return formatYmdWithDow(periodKey);
  }
  return periodKey;
}

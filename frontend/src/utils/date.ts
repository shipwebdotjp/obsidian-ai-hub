export function formatYmdWithDow(ymd: string): string {
  const match = ymd.match(/^\d{4}-\d{2}-\d{2}$/);
  if (!match) return ymd;
  const parts = ymd.split("-").map(Number);
  const year = parts[0]!;
  const month = parts[1]!;
  const day = parts[2]!;
  const date = new Date(`${ymd}T00:00:00`);
  if (date.getFullYear() !== year || date.getMonth() + 1 !== month || date.getDate() !== day) {
    return ymd;
  }
  const weekdays = ["日", "月", "火", "水", "木", "金", "土"];
  const dow = weekdays[date.getDay()];
  if (dow === undefined) return ymd;
  return ymd.replace(/-/g, "/") + `(${dow})`;
}

export function formatDateTime(isoString: string): string {
  if (!isoString) return "";
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return "";
  const weekdays = ["日", "月", "火", "水", "木", "金", "土"];
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const dow = weekdays[date.getDay()];
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${y}/${m}/${d}(${dow}) ${hh}:${mm}`;
}

export function formatScore(score: number): string {
  return score.toFixed(4);
}

/** 更新日時を `Y/m/d H:i`（秒なし）で表示する。 */
export function formatMtime(mtime: number): string {
  const d = new Date(mtime * 1000);
  if (Number.isNaN(d.getTime())) return String(mtime);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

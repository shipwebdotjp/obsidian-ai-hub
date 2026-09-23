export function formatScore(score: number): string {
  return score.toFixed(4);
}

export function formatMtime(mtime: number): string {
  try {
    const d = new Date(mtime * 1000);
    return d.toLocaleString("ja-JP");
  } catch {
    return String(mtime);
  }
}

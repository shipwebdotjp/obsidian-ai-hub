const RESEARCH_STATUS_LABELS: Record<string, string> = {
  candidate: "候補",
  approved: "承認済み",
  rejected: "却下済み",
  duplicate: "重複",
};

export function researchStatusLabel(status: string): string {
  return RESEARCH_STATUS_LABELS[status] ?? status;
}

const RESEARCH_JOB_STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  succeeded: "bg-emerald-100 text-emerald-800",
  failed: "bg-rose-100 text-rose-800",
};

export function researchJobStatusColor(status: string): string {
  return RESEARCH_JOB_STATUS_COLORS[status] ?? "bg-slate-100";
}

const RESEARCH_JOB_STATUS_LABELS: Record<string, string> = {
  pending: "実行待ち",
  running: "実行中",
  succeeded: "リサーチ済み",
  failed: "失敗",
};

export function researchJobStatusLabel(status: string): string {
  return RESEARCH_JOB_STATUS_LABELS[status] ?? status;
}

const RESEARCH_MODE_LABELS: Record<string, string> = {
  auto: "自動",
  internal: "内省",
  web: "ウェブ検索",
  deep: "ディープリサーチ",
  project: "コードベース調査",
};

export function researchModeLabel(mode: string): string {
  return RESEARCH_MODE_LABELS[mode] ?? mode;
}

export function isResearchSucceeded(job?: { status?: string } | null): boolean {
  return job?.status === "succeeded";
}

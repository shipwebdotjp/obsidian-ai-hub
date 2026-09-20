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

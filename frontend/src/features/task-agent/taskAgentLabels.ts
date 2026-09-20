export const TERMINAL_STATUSES = [
  "completed",
  "incomplete",
  "failed",
  "cancelled",
] as const;

export const NON_TERMINAL_FILTER = "__non_terminal__";

export const TASK_STATUS_LABELS: Record<string, string> = {
  queued: "受付済み",
  planning: "計画中",
  waiting_user: "質問回答待ち",
  waiting_approval: "承認待ち",
  ready: "実行待ち",
  running: "実行中",
  waiting_reapproval: "再承認待ち",
  cancelling: "取消中",
  interrupted: "中断",
  completed: "完了",
  failed: "失敗",
  cancelled: "取消済み",
  incomplete: "未完了",
};

const GREEN_STATUSES = new Set(["completed", "ready"]);
const YELLOW_STATUSES = new Set([
  "queued",
  "planning",
  "waiting_user",
  "waiting_approval",
  "waiting_reapproval",
  "cancelling",
  "interrupted",
]);
const BLUE_STATUSES = new Set(["running"]);
const RED_STATUSES = new Set(["failed"]);
const AMBER_STATUSES = new Set(["incomplete"]);
const GRAY_STATUSES = new Set(["cancelled"]);

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABELS[status] ?? status;
}

export function taskStatusBadgeClass(status: string): string {
  const base = "rounded-full px-2 py-0.5 text-[10px] font-medium";
  if (GREEN_STATUSES.has(status)) return `${base} bg-emerald-100 text-emerald-800`;
  if (YELLOW_STATUSES.has(status)) return `${base} bg-yellow-100 text-yellow-800`;
  if (BLUE_STATUSES.has(status)) return `${base} bg-blue-100 text-blue-800`;
  if (RED_STATUSES.has(status)) return `${base} bg-rose-100 text-rose-800`;
  if (AMBER_STATUSES.has(status)) return `${base} bg-amber-100 text-amber-800`;
  if (GRAY_STATUSES.has(status)) return `${base} bg-slate-100 text-slate-600`;
  return `${base} bg-slate-100 text-slate-600`;
}

export const EVENT_TYPE_LABELS: Record<string, string> = {
  status_changed: "状態変更",
  plan_created: "Plan作成",
  plan_approved: "Plan承認",
  plan_rejected: "Plan差戻し",
  child_run_started: "子run開始",
  child_run_finished: "子run終了",
  hitl_question_asked: "質問登録",
  hitl_question_answered: "質問回答",
  target_resolution_selected: "対象確定",
  capability_completed: "Capability完了",
  note: "メモ",
};

export function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABELS[eventType] ?? eventType;
}

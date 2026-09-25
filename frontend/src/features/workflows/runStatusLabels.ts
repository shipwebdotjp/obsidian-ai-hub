import type { WorkflowRunStatus } from "../../api/types";

/** Japanese display labels for Run states. */
export const RUN_STATUS_LABELS: Record<WorkflowRunStatus, string> = {
  queued: "待機",
  waiting_approval: "承認待ち",
  running: "実行中",
  waiting_hitl: "回答待ち",
  waiting_attention: "対応待ち",
  cancelling: "停止要求中",
  interrupted: "中断",
  completed: "完了",
  incomplete: "未完了",
  failed: "失敗",
  cancelled: "取消",
};

/** Label lookup that degrades to the raw status for unknown values. */
export function runStatusLabel(status: WorkflowRunStatus | string): string {
  return RUN_STATUS_LABELS[status as WorkflowRunStatus] ?? status;
}

/** Run states whose history can be deleted (mirrors backend RUN_TERMINAL_STATUSES). */
export const TERMINAL_RUN_STATUSES: ReadonlySet<WorkflowRunStatus> = new Set([
  "completed",
  "incomplete",
  "failed",
  "cancelled",
]);

/** Terminal check for loosely-typed values (e.g. refs held as string). */
export function isTerminalRunStatus(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status as WorkflowRunStatus);
}

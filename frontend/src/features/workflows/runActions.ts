import { deleteWorkflowRun } from "../../api/client";

/**
 * Confirm and delete one terminal Run.
 *
 * The message lives here so the Workflow detail list and the Run page cannot
 * drift. Returns false when the user cancels.
 */
export async function confirmAndDeleteRun(runId: string): Promise<boolean> {
  if (
    !window.confirm(
      "この Run と実行履歴を削除しますか？この操作は取り消せません。" +
        "子の Agent / Coding / HITL 実行は削除されません。",
    )
  ) {
    return false;
  }
  await deleteWorkflowRun(runId);
  return true;
}

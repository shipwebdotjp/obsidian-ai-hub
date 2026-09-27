import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getWorkflow, updateWorkflow } from "../../api/client";
import type { WorkflowDetail } from "../../api/types";
import { workflowDetailPath } from "../../constants/routes";
import { getApiErrorMessage } from "../../utils/error";

/**
 * Compact workflow header shown on child pages (editor / run). Surfaces the
 * workflow name and the approval-skip setting without leaving the page.
 */
export function WorkflowHeaderBar({ workflowId }: { workflowId: string }) {
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setWorkflow(await getWorkflow(workflowId));
      setError(null);
    } catch (e) {
      setError(getApiErrorMessage(e, "ワークフローの読み込みに失敗しました"));
    }
  }, [workflowId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onToggleSkip = async (next: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setWorkflow(await updateWorkflow(workflowId, { skip_approval: next }));
    } catch (e) {
      setError(getApiErrorMessage(e, "設定の更新に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  if (!workflow) {
    return error ? (
      <p className="border-b border-slate-200 bg-white px-4 py-1.5 text-xs text-rose-700">
        {error}
      </p>
    ) : null;
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-1.5 text-xs">
      <div className="flex min-w-0 items-center gap-2">
        <Link
          to={workflowDetailPath(workflow.workflow_id)}
          className="shrink-0 font-semibold text-slate-800 hover:underline"
        >
          {workflow.name}
        </Link>
        {workflow.description && (
          <span className="truncate text-slate-500">{workflow.description}</span>
        )}
      </div>
      <div className="flex flex-col items-end">
        <label
          className="flex cursor-pointer items-center gap-1 text-slate-700"
          title="以降の Run（Scheduler を含む）に適用されます。既存の Run には影響しません。"
        >
          <input
            type="checkbox"
            data-testid="workflow-skip-approval"
            className="cursor-pointer disabled:cursor-not-allowed"
            disabled={busy}
            checked={workflow.skip_approval}
            onChange={(event) => void onToggleSkip(event.target.checked)}
          />
          承認なしで実行する
        </label>
        <span className="text-[10px] text-slate-400">
          以降の Run に適用
        </span>
        {error && <span className="text-[10px] text-rose-700">{error}</span>}
      </div>
    </div>
  );
}

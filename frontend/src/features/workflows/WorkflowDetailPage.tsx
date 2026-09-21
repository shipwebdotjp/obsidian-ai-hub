import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  createWorkflowRevision,
  deleteWorkflowRevision,
  getWorkflow,
} from "../../api/client";
import type { WorkflowDetail } from "../../api/types";
import {
  workflowEditPath,
  workflowRunPath,
} from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";
import { REVISION_STATUS_LABEL } from "./revisionLabels";

export default function WorkflowDetailPage() {
  const { workflowId = "" } = useParams();
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    setError(null);
    try {
      setWorkflow(await getWorkflow(workflowId));
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    }
  }, [workflowId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onNewRevision = async () => {
    setBusy(true);
    try {
      await createWorkflowRevision(workflowId);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "Revision 作成に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onDeleteRevision = async (revisionId: string, version: number, status: string) => {
    const statusLabel = REVISION_STATUS_LABEL[status] ?? status;
    if (
      !window.confirm(
        `v${version}（${statusLabel}）を完全に削除しますか？この操作は取り消せません。`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await deleteWorkflowRevision(revisionId);
      await reload();
    } catch (e) {
      setError(getApiErrorMessage(e, "Revision 削除に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  if (!workflow) {
    return (
      <div className="p-4 text-sm text-slate-500">
        {error ?? "読み込み中…"}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-auto bg-slate-50">
      <header className="border-b border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">{workflow.name}</h1>
            <p className="text-xs text-slate-500">{workflow.description}</p>
          </div>
          <button
            type="button"
            onClick={onNewRevision}
            disabled={busy}
            className="cursor-pointer rounded bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-700 disabled:opacity-50"
          >
            新しい下書き
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
      </header>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Revision</h2>
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {(workflow.revisions ?? []).map((revision) => (
            <li
              key={revision.revision_id}
              className="flex items-center justify-between px-3 py-2 text-sm"
            >
              <span>
                v{revision.version} ・{" "}
                {REVISION_STATUS_LABEL[revision.status] ?? revision.status}
              </span>
              <span className="flex items-center gap-2">
                {revision.status === "draft" ? (
                  <Link
                    className="text-blue-700"
                    to={workflowEditPath(revision.revision_id)}
                  >
                    編集
                  </Link>
                ) : (
                  <span className="text-slate-400">編集不可</span>
                )}
                {revision.status !== "published" && (
                  <button
                    type="button"
                    onClick={() =>
                      onDeleteRevision(
                        revision.revision_id,
                        revision.version,
                        revision.status,
                      )
                    }
                    disabled={busy}
                    className="cursor-pointer rounded bg-rose-800 px-2 py-0.5 text-xs text-white disabled:opacity-50"
                  >
                    削除
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Run</h2>
        {(workflow.runs ?? []).length === 0 ? (
          <p className="text-xs text-slate-500">Run はありません。</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
            {(workflow.runs ?? []).map((run) => (
              <li
                key={run.run_id}
                className="flex items-center justify-between px-3 py-2 text-sm"
              >
                <span>
                  {run.status} ・ {formatDateTime(run.created_at)}
                </span>
                <Link className="text-blue-700" to={workflowRunPath(run.run_id)}>
                  詳細
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

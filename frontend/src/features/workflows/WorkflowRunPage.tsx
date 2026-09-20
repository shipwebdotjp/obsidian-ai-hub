import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  approveWorkflowRun,
  cancelWorkflowRun,
  getWorkflowRun,
  resolveWorkflowAttention,
  resumeWorkflowRun,
} from "../../api/client";
import type { WorkflowRun } from "../../api/types";
import { ROUTES } from "../../constants/routes";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";

const TERMINAL = new Set(["completed", "incomplete", "failed", "cancelled"]);

export default function WorkflowRunPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      setRun(await getWorkflowRun(runId));
      setError(null);
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    }
  }, [runId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!run || TERMINAL.has(run.status)) return;
    const timer = window.setInterval(() => void reload(), 3000);
    return () => window.clearInterval(timer);
  }, [run, reload]);

  const act = async (action: () => Promise<WorkflowRun>) => {
    setBusy(true);
    try {
      await action();
      await reload();
      setError(null);
    } catch (e) {
      setError(getApiErrorMessage(e, "操作に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  if (!run) {
    return (
      <div className="p-4 text-sm text-slate-500">
        {error ?? "読み込み中…"}
      </div>
    );
  }

  const attentionNode = (run.nodes ?? []).find(
    (node) => node.status === "needs_attention",
  );

  return (
    <div className="flex h-full flex-col overflow-auto bg-slate-50">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <div className="text-sm">
          <span className="font-semibold">Run</span> {run.run_id} ・ {run.status}
        </div>
        <div className="flex flex-wrap gap-2">
          {run.status === "waiting_approval" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => approveWorkflowRun(runId))}
              className="cursor-pointer rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50"
            >
              承認
            </button>
          )}
          {run.status === "interrupted" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => resumeWorkflowRun(runId))}
              className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-xs text-white disabled:opacity-50"
            >
              再開
            </button>
          )}
          {!TERMINAL.has(run.status) && (
            <button
              type="button"
              disabled={busy}
              onClick={() => act(() => cancelWorkflowRun(runId))}
              className="cursor-pointer rounded bg-rose-800 px-3 py-1 text-xs text-white disabled:opacity-50"
            >
              取消
            </button>
          )}
          {run.status === "waiting_attention" && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act(() => resolveWorkflowAttention(runId, { decision: "adopt" }))
                }
                className="cursor-pointer rounded bg-emerald-600 px-3 py-1 text-xs text-white disabled:opacity-50"
              >
                採用して続行
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act(() => resolveWorkflowAttention(runId, { decision: "reexecute" }))
                }
                className="cursor-pointer rounded bg-amber-600 px-3 py-1 text-xs text-white disabled:opacity-50"
              >
                再実行
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  act(() => resolveWorkflowAttention(runId, { decision: "fail" }))
                }
                className="cursor-pointer rounded bg-rose-800 px-3 py-1 text-xs text-white disabled:opacity-50"
              >
                失敗として処理
              </button>
            </>
          )}
          <Link className="rounded border border-slate-300 px-3 py-1 text-xs" to={ROUTES.WORKFLOWS}>
            一覧
          </Link>
        </div>
      </header>

      {error && <p className="bg-white px-4 py-2 text-xs text-rose-700">{error}</p>}
      {attentionNode && (
        <p className="bg-white px-4 py-2 text-xs text-amber-700">
          Node {attentionNode.node_id} が対応待ちです。
        </p>
      )}

      <section className="px-4 py-3 text-xs">
        <h2 className="mb-1 text-sm font-semibold">概要</h2>
        <div>作成: {formatDateTime(run.created_at)}</div>
        {run.result_summary && <div>結果: {run.result_summary}</div>}
        {run.error_summary && <div className="text-rose-700">エラー: {run.error_summary}</div>}
        <pre className="mt-2 overflow-auto rounded bg-white p-2 text-[11px]">
          {JSON.stringify(run.inputs, null, 2)}
        </pre>
      </section>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Node</h2>
        <table className="w-full border-collapse bg-white text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="border-b border-slate-200 px-2 py-1">node</th>
              <th className="border-b border-slate-200 px-2 py-1">status</th>
              <th className="border-b border-slate-200 px-2 py-1">attempt</th>
              <th className="border-b border-slate-200 px-2 py-1">output</th>
            </tr>
          </thead>
          <tbody>
            {(run.nodes ?? []).map((node) => (
              <tr key={`${node.activation_id}-${node.attempt}`}>
                <td className="border-b border-slate-100 px-2 py-1">
                  {node.node_id.slice(0, 8)}
                </td>
                <td className="border-b border-slate-100 px-2 py-1">{node.status}</td>
                <td className="border-b border-slate-100 px-2 py-1">{node.attempt}</td>
                <td className="max-w-md truncate border-b border-slate-100 px-2 py-1 font-mono text-[10px]">
                  {node.output_json ?? node.error_summary ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">Events</h2>
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {(run.events ?? []).map((event) => (
            <li key={event.event_id} className="px-2 py-1 text-xs">
              <span className="font-mono">{event.event_type}</span>{" "}
              <span className="text-slate-500">
                {JSON.stringify(event.payload)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

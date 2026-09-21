import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  approveWorkflowRun,
  cancelWorkflowRun,
  getWorkflowRun,
  rerunWorkflowRun,
  resolveWorkflowAttention,
  resumeWorkflowRun,
} from "../../api/client";
import type { WorkflowRun } from "../../api/types";
import { ROUTES, workflowRunPath } from "../../constants/routes";
import {
  loadLastAppliedId,
  saveLastAppliedId,
  subscribeRunEvents,
} from "../../api/runSse";
import { formatDateTime } from "../../utils/date";
import { getApiErrorMessage } from "../../utils/error";
import { nodeDisplayName } from "./graphModel";
import {
  aggregateNodeStates,
  historyForNode,
  initialSelectedNodeId,
  layoutRunGraph,
  RUN_GRAPH_STATUS_LABELS,
  runGraphOf,
} from "./runGraphModel";
import InputsSchemaForm from "./InputsSchemaForm";
import WorkflowCanvas from "./WorkflowCanvas";

const TERMINAL = new Set(["completed", "incomplete", "failed", "cancelled"]);

export default function WorkflowRunPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [rerunInputs, setRerunInputs] = useState<Record<string, unknown>>({});
  const [rerunErrors, setRerunErrors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectionTouched = useRef(false);

  const reload = useCallback(async () => {
    try {
      setRun(await getWorkflowRun(runId));
      setError(null);
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    }
  }, [runId]);

  const reloadRef = useRef(reload);
  useEffect(() => {
    reloadRef.current = reload;
  }, [reload]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const [generation, setGeneration] = useState(0);
  const statusRef = useRef("");
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    statusRef.current = run?.status ?? "";
  }, [run]);

  const scheduleReload = useCallback(() => {
    if (debounceRef.current !== null) return;
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      void reloadRef.current();
    }, 500);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let resubscribeTimer: number | null = null;
    const stream = async () => {
      try {
        await subscribeRunEvents({
          url: `/api/v1/workflows/runs/${encodeURIComponent(runId)}/stream`,
          lastEventId: loadLastAppliedId("workflow", runId),
          signal: controller.signal,
          onEnvelope: (envelope) => {
            saveLastAppliedId("workflow", runId, envelope.eventId);
            scheduleReload();
          },
        });
      } catch (e) {
        if (!disposed) setError(getApiErrorMessage(e, "進捗の取得に失敗しました"));
        return;
      }
      if (disposed) return;
      await reloadRef.current();
      if (disposed) return;
      // The server closes the stream on terminal or waiting state. While the
      // run is still active, re-subscribe from the saved cursor.
      if (["queued", "running", "cancelling"].includes(statusRef.current)) {
        resubscribeTimer = window.setTimeout(
          () => setGeneration((value) => value + 1),
          1000,
        );
      }
    };
    void stream();
    const poll = window.setInterval(() => {
      if (TERMINAL.has(statusRef.current)) return;
      void reloadRef.current();
    }, 10000);
    return () => {
      disposed = true;
      controller.abort();
      if (resubscribeTimer !== null) window.clearTimeout(resubscribeTimer);
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      window.clearInterval(poll);
    };
  }, [runId, generation, scheduleReload]);

  const act = async (action: () => Promise<WorkflowRun>) => {
    setBusy(true);
    try {
      const updated = await action();
      await reload();
      setError(null);
      if (!TERMINAL.has(updated.status)) {
        setGeneration((value) => value + 1);
      }
    } catch (e) {
      setError(getApiErrorMessage(e, "操作に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const onRerun = async () => {
    setBusy(true);
    try {
      const created = await rerunWorkflowRun(runId, rerunInputs);
      navigate(workflowRunPath(created.run_id));
    } catch (e) {
      const detail = (e as { body?: { detail?: { errors?: string[] } } })?.body
        ?.detail;
      setRerunErrors(Array.isArray(detail?.errors) ? detail.errors : []);
      setError(getApiErrorMessage(e, "再実行に失敗しました"));
    } finally {
      setBusy(false);
    }
  };

  const runNodes = run?.nodes ?? [];
  const graphNodes = useMemo(() => (run ? runGraphOf(run) : null), [run]);
  const nodeStates = useMemo(() => aggregateNodeStates(runNodes), [runNodes]);
  const nodeStatesRecord = useMemo(
    () => Object.fromEntries(nodeStates),
    [nodeStates],
  );
  const graphLayout = useMemo(
    () => (graphNodes ? layoutRunGraph(graphNodes.nodes) : null),
    [graphNodes],
  );

  useEffect(() => {
    setSelectedNodeId(null);
    selectionTouched.current = false;
  }, [runId]);

  useEffect(() => {
    if (selectionTouched.current || !graphNodes) return;
    setSelectedNodeId(
      initialSelectedNodeId(
        graphNodes.nodes.map((node) => node.node_id),
        runNodes,
        nodeStates,
      ),
    );
  }, [graphNodes, runNodes, nodeStates]);

  if (!run) {
    return (
      <div className="p-4 text-sm text-slate-500">
        {error ?? "読み込み中…"}
      </div>
    );
  }

  const selectedNode =
    graphNodes?.nodes.find((node) => node.node_id === selectedNodeId) ??
    null;
  const selectedState = selectedNodeId
    ? nodeStates.get(selectedNodeId)
    : undefined;
  const visibleRunNodes =
    graphNodes && selectedNodeId
      ? historyForNode(runNodes, selectedNodeId)
      : runNodes;

  const attentionNode = runNodes.find(
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
          {TERMINAL.has(run.status) && (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                setRerunOpen((value) => {
                  if (!value) {
                    setRerunInputs(run.inputs ?? {});
                    setRerunErrors([]);
                  }
                  return !value;
                })
              }
              className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-50"
            >
              再実行
            </button>
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

      {rerunOpen && (
        <section className="border-b border-slate-200 bg-white px-4 py-3 text-xs">
          <h2 className="mb-2 text-sm font-semibold">再実行の入力</h2>
          <InputsSchemaForm
            schema={run.graph_snapshot?.inputs_schema ?? { type: "object" }}
            values={rerunInputs}
            onChange={setRerunInputs}
            errors={rerunErrors}
          />
          <button
            type="button"
            disabled={busy}
            onClick={onRerun}
            className="mt-2 cursor-pointer rounded bg-blue-600 px-3 py-1 text-xs text-white disabled:opacity-50"
          >
            この入力で再実行
          </button>
        </section>
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

      {graphNodes && graphLayout && (
        <section className="border-b border-slate-200 bg-white px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">グラフ</h2>
            {selectedNodeId && (
              <button
                type="button"
                data-testid="run-graph-clear-selection"
                onClick={() => {
                  selectionTouched.current = true;
                  setSelectedNodeId(null);
                }}
                className="cursor-pointer rounded border border-slate-300 px-3 py-1 text-xs"
              >
                選択を解除
              </button>
            )}
          </div>
          <WorkflowCanvas
            nodes={graphNodes.nodes}
            edges={graphNodes.edges}
            selectedNodeId={selectedNodeId}
            onSelectNode={(nodeId) => {
              selectionTouched.current = true;
              setSelectedNodeId(nodeId);
            }}
            readOnly
            nodeStates={nodeStatesRecord}
            positions={graphLayout.positions}
            canvasWidth={graphLayout.width}
            canvasHeight={graphLayout.height}
          />
          {selectedNode && (
            <div
              data-testid="run-node-detail"
              className="mt-2 rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
            >
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                <span className="font-semibold">
                  {nodeDisplayName(selectedNode)}
                </span>
                <span className="text-slate-500">{selectedNode.node_type}</span>
                {selectedState && selectedState.status !== "unexecuted" && (
                  <span className="text-slate-600">
                    状態: {RUN_GRAPH_STATUS_LABELS[selectedState.status]} /
                    attempt {selectedState.latestAttempt}
                    {selectedState.activationCount > 1 &&
                      ` / 実行 ${selectedState.activationCount} 回`}
                  </span>
                )}
              </div>
              <div className="mt-1 break-all font-mono text-[11px] text-slate-600">
                {selectedNode.node_id}
              </div>
            </div>
          )}
        </section>
      )}

      <section className="px-4 py-3">
        <h2 className="mb-2 text-sm font-semibold">
          Node{selectedNode ? `: ${nodeDisplayName(selectedNode)}` : ""}
        </h2>
        <table className="w-full border-collapse bg-white text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="border-b border-slate-200 px-2 py-1">
                {graphNodes && selectedNodeId ? "activation" : "node"}
              </th>
              <th className="border-b border-slate-200 px-2 py-1">status</th>
              <th className="border-b border-slate-200 px-2 py-1">attempt</th>
              <th className="border-b border-slate-200 px-2 py-1">output</th>
            </tr>
          </thead>
          <tbody>
            {visibleRunNodes.map((node) => (
              <tr key={`${node.activation_id}-${node.attempt}`}>
                <td className="border-b border-slate-100 px-2 py-1">
                  {graphNodes && selectedNodeId
                    ? node.activation_id.slice(0, 8)
                    : node.node_id.slice(0, 8)}
                </td>
                <td className="border-b border-slate-100 px-2 py-1">{node.status}</td>
                <td className="border-b border-slate-100 px-2 py-1">{node.attempt}</td>
                <td className="max-w-md truncate border-b border-slate-100 px-2 py-1 font-mono text-[10px]">
                  {node.output_json ?? node.error_summary ?? ""}
                </td>
              </tr>
            ))}
            {visibleRunNodes.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  data-testid="run-node-empty"
                  className="border-b border-slate-100 px-2 py-1 text-slate-500"
                >
                  このノードの実行履歴はありません
                </td>
              </tr>
            )}
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

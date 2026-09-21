import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getWorkflowRevision,
  listAgents,
  listWorkflowCapabilities,
  publishWorkflowRevision,
  updateWorkflowRevision,
  validateWorkflowRevision,
  createWorkflowRun,
  deleteWorkflowRevision,
} from "../../api/client";
import type {
  Agent,
  WorkflowCapabilityRecord,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowRevision,
} from "../../api/types";
import { workflowDetailPath, workflowRunPath } from "../../constants/routes";
import { getApiErrorMessage } from "../../utils/error";
import { revisionStatusLabel } from "./revisionLabels";
import ConditionEditor from "./ConditionEditor";
import InputsSchemaForm from "./InputsSchemaForm";
import WorkflowCanvas from "./WorkflowCanvas";
import {
  conditionCandidates,
  createNode,
  createEdge,
  defaultInputsSchema,
  moveNode,
  removeNode,
  scopeOf,
  validateGraphShape,
  type GraphIssue,
} from "./graphModel";

const NODE_TYPES: WorkflowNodeType[] = [
  "capability",
  "agent",
  "loop",
  "terminal",
  "loop_result",
];

function JsonArea({
  label,
  value,
  onCommit,
}: {
  label: string;
  value: unknown;
  onCommit: (value: unknown) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
  }, [value]);
  return (
    <label className="block text-xs">
      <span className="mb-1 block text-slate-700">{label}</span>
      <textarea
        className="h-28 w-full rounded border border-slate-300 px-2 py-1 font-mono text-[11px]"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          try {
            onCommit(JSON.parse(event.target.value));
            setError(null);
          } catch {
            setError("JSON が不正です");
          }
        }}
      />
      {error && <span className="text-rose-700">{error}</span>}
    </label>
  );
}

export default function WorkflowEditorPage() {
  const { revisionId = "" } = useParams();
  const navigate = useNavigate();
  const [revision, setRevision] = useState<WorkflowRevision | null>(null);
  const [nodes, setNodes] = useState<WorkflowNode[]>([]);
  const [edges, setEdges] = useState<WorkflowEdge[]>([]);
  const [inputsSchema, setInputsSchema] = useState<Record<string, unknown>>(
    defaultInputsSchema(),
  );
  const [capabilities, setCapabilities] = useState<WorkflowCapabilityRecord[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [newNodeType, setNewNodeType] = useState<WorkflowNodeType>("capability");
  const [newCapabilityKey, setNewCapabilityKey] = useState("");
  const [newAgentId, setNewAgentId] = useState("");
  const [parentLoopId, setParentLoopId] = useState("");
  const [edgeSource, setEdgeSource] = useState("");
  const [edgeTarget, setEdgeTarget] = useState("");
  const [edgeKind, setEdgeKind] = useState<"normal" | "error">("normal");
  const [edgeCondition, setEdgeCondition] = useState<Record<string, unknown> | null>(null);
  const [editingEdgeId, setEditingEdgeId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [serverIssues, setServerIssues] = useState<string[]>([]);
  const [runInputs, setRunInputs] = useState<Record<string, unknown>>({});
  const [runErrors, setRunErrors] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [rev, caps, agentRes] = await Promise.all([
        getWorkflowRevision(revisionId),
        listWorkflowCapabilities(),
        listAgents(),
      ]);
      setRevision(rev);
      setNodes(rev.nodes);
      setEdges(rev.edges);
      setInputsSchema(rev.inputs_schema ?? defaultInputsSchema());
      setCapabilities(caps.items);
      setAgents(agentRes.agents);
      setDirty(false);
    } catch (e) {
      setError(getApiErrorMessage(e, "読み込みに失敗しました"));
    }
  }, [revisionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const loops = useMemo(
    () => nodes.filter((node) => node.node_type === "loop"),
    [nodes],
  );
  const selectedNode = nodes.find((node) => node.node_id === selectedNodeId) ?? null;
  const localIssues: GraphIssue[] = useMemo(
    () => validateGraphShape(nodes, edges, inputsSchema),
    [nodes, edges, inputsSchema],
  );

  const markDirty = () => setDirty(true);

  const onAddNode = () => {
    const position = { x: 40 + (nodes.length % 4) * 220, y: 40 + Math.floor(nodes.length / 4) * 110 };
    const node = createNode(
      newNodeType,
      position,
      newNodeType === "capability" ? newCapabilityKey : undefined,
      parentLoopId || null,
    );
    if (newNodeType === "agent" && newAgentId) {
      node.config = { ...node.config, agent_id: newAgentId };
    }
    setNodes((prev) => [...prev, node]);
    setSelectedNodeId(node.node_id);
    markDirty();
  };

  const onDeleteNode = () => {
    if (!selectedNodeId) return;
    const result = removeNode(nodes, edges, selectedNodeId);
    setNodes(result.nodes);
    setEdges(result.edges);
    setSelectedNodeId(null);
    markDirty();
  };

  const onAddEdge = () => {
    if (!edgeSource || !edgeTarget || edgeSource === edgeTarget) return;
    const order = edges.filter((edge) => edge.source_node_id === edgeSource).length;
    setEdges((prev) => [
      ...prev,
      {
        ...createEdge(edgeSource, edgeTarget, order),
        edge_kind: edgeKind,
        condition: edgeCondition,
      },
    ]);
    setEdgeCondition(null);
    markDirty();
  };

  const updateNodeConfig = (patch: Record<string, unknown>) => {
    if (!selectedNode) return;
    setNodes((prev) =>
      prev.map((node) =>
        node.node_id === selectedNode.node_id
          ? { ...node, config: { ...node.config, ...patch } }
          : node,
      ),
    );
    markDirty();
  };

  const save = useCallback(async (): Promise<boolean> => {
    setError(null);
    // Published/superseded revisions are immutable; a run must not be blocked
    // by an impossible save. Local edits to non-draft revisions are not saved.
    if (revision?.status !== "draft") {
      setStatus("公開済み/旧リビジョンのため保存されません");
      return true;
    }
    try {
      const updated = await updateWorkflowRevision(revisionId, {
        inputs_schema: inputsSchema,
        nodes,
        edges,
      });
      setRevision(updated);
      setDirty(false);
      setStatus("保存しました");
      return true;
    } catch (e) {
      setError(getApiErrorMessage(e, "保存に失敗しました"));
      return false;
    }
  }, [revisionId, revision?.status, inputsSchema, nodes, edges]);

  const onValidate = async () => {
    setServerIssues([]);
    if (dirty && !(await save())) return;
    try {
      const res = await validateWorkflowRevision(revisionId);
      setServerIssues(res.errors);
      setStatus(res.valid ? "検証 OK" : "検証エラーがあります");
    } catch (e) {
      setError(getApiErrorMessage(e, "検証に失敗しました"));
    }
  };

  const onPublish = async () => {
    if (!(await save())) return;
    try {
      setRevision(await publishWorkflowRevision(revisionId));
      setStatus("公開しました");
    } catch (e) {
      setError(getApiErrorMessage(e, "公開に失敗しました"));
    }
  };

  const onStart = async () => {
    if (!(await save())) return;
    setRunErrors([]);
    try {
      const run = await createWorkflowRun(revisionId, runInputs);
      navigate(workflowRunPath(run.run_id));
    } catch (e) {
      setRunErrors(
        e instanceof Error ? [e.message] : ["Run 作成に失敗しました"],
      );
    }
  };

  const onDelete = async () => {
    if (!revision || revision.status === "published") return;
    const statusLabel = revisionStatusLabel(revision.status);
    if (
      !window.confirm(
        `v${revision.version}（${statusLabel}）を完全に削除しますか？この操作は取り消せません。` +
          (dirty ? "未保存の変更も破棄されます。" : ""),
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await deleteWorkflowRevision(revisionId);
      navigate(workflowDetailPath(revision.workflow_id));
    } catch (e) {
      setError(getApiErrorMessage(e, "削除に失敗しました"));
    } finally {
      setDeleting(false);
    }
  };

  if (!revision) {
    return (
      <div className="p-4 text-sm text-slate-500">
        {error ?? "読み込み中…"}
      </div>
    );
  }

  const targetsInScope = (sourceId: string) => {
    const source = nodes.find((node) => node.node_id === sourceId);
    if (!source) return [];
    return nodes.filter((node) => scopeOf(node) === scopeOf(source) && node.node_id !== sourceId);
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2">
        <div className="text-sm font-semibold">
          {revision.workflow_id} / v{revision.version} ({revision.status})
          {dirty && <span className="ml-2 text-xs text-amber-700">未保存</span>}
          {revision.status !== "draft" && (
            <span className="ml-2 text-xs font-normal text-slate-500">
              このリビジョンは編集できません（実行のみ）
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={save} className="cursor-pointer rounded bg-slate-900 px-3 py-1 text-xs text-white">
            保存
          </button>
          <button type="button" onClick={onValidate} className="cursor-pointer rounded border border-slate-300 bg-white px-3 py-1 text-xs">
            検証
          </button>
          <button type="button" onClick={onPublish} className="cursor-pointer rounded bg-emerald-600 px-3 py-1 text-xs text-white">
            公開
          </button>
          <button type="button" onClick={onStart} className="cursor-pointer rounded bg-blue-600 px-3 py-1 text-xs text-white">
            実行
          </button>
          {revision.status !== "published" && (
            <button type="button" onClick={onDelete} disabled={deleting} className="cursor-pointer rounded bg-rose-800 px-3 py-1 text-xs text-white disabled:opacity-50">
              削除
            </button>
          )}
        </div>
      </header>

      {(error || status || localIssues.length > 0 || serverIssues.length > 0) && (
        <div className="border-b border-slate-200 bg-white px-4 py-2 text-xs">
          {error && <p className="text-rose-700">{error}</p>}
          {status && <p className="text-slate-600">{status}</p>}
          {localIssues.length > 0 && (
            <ul data-testid="workflow-local-issues" className="text-amber-700">
              {localIssues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}>{issue.message}</li>
              ))}
            </ul>
          )}
          {serverIssues.length > 0 && (
            <ul data-testid="workflow-server-issues" className="text-rose-700">
              {serverIssues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-auto p-3">
          <WorkflowCanvas
            nodes={nodes}
            edges={edges}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onMoveNode={(nodeId, position) => {
              setNodes((prev) => moveNode(prev, nodeId, position));
              markDirty();
            }}
          />
        </div>

        <aside className="w-96 shrink-0 space-y-3 overflow-auto border-l border-slate-200 bg-white p-3 text-xs">
          <section className="space-y-2">
            <h3 className="font-semibold">Node 追加</h3>
            <div className="flex flex-wrap gap-2">
              <select
                className="rounded border border-slate-300 px-1 py-0.5"
                value={newNodeType}
                onChange={(event) =>
                  setNewNodeType(event.target.value as WorkflowNodeType)
                }
              >
                {NODE_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
              {newNodeType === "capability" && (
                <select
                  className="rounded border border-slate-300 px-1 py-0.5"
                  value={newCapabilityKey}
                  onChange={(event) => setNewCapabilityKey(event.target.value)}
                >
                  <option value="">capability を選択</option>
                  {capabilities
                    .filter((c) => c.enabled)
                    .map((c) => (
                      <option key={c.capability_key} value={c.capability_key}>
                        {c.capability_key}
                        {c.approval_policy === "plan_required" ? " (要承認)" : ""}
                      </option>
                    ))}
                </select>
              )}
              {newNodeType === "agent" && (
                <select
                  className="rounded border border-slate-300 px-1 py-0.5"
                  value={newAgentId}
                  onChange={(event) => setNewAgentId(event.target.value)}
                >
                  <option value="">Agent を選択</option>
                  {agents.map((agent) => (
                    <option key={agent.agent_id} value={agent.agent_id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              )}
              <select
                className="rounded border border-slate-300 px-1 py-0.5"
                value={parentLoopId}
                onChange={(event) => setParentLoopId(event.target.value)}
              >
                <option value="">親: トップ</option>
                {loops.map((loop) => (
                  <option key={loop.node_id} value={loop.node_id}>
                    親Loop {loop.node_id.slice(0, 6)}
                  </option>
                ))}
              </select>
              <button type="button" onClick={onAddNode} className="cursor-pointer rounded bg-blue-600 px-2 py-1 text-white">
                追加
              </button>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="font-semibold">Edge 追加</h3>
            <select
              className="w-full rounded border border-slate-300 px-1 py-0.5"
              value={edgeSource}
              onChange={(event) => {
                setEdgeSource(event.target.value);
                setEdgeTarget("");
              }}
            >
              <option value="">source</option>
              {nodes.map((node) => (
                <option key={node.node_id} value={node.node_id}>
                  {node.node_type} {node.node_id.slice(0, 6)}
                </option>
              ))}
            </select>
            <select
              className="w-full rounded border border-slate-300 px-1 py-0.5"
              value={edgeTarget}
              onChange={(event) => setEdgeTarget(event.target.value)}
            >
              <option value="">target</option>
              {targetsInScope(edgeSource).map((node) => (
                <option key={node.node_id} value={node.node_id}>
                  {node.node_type} {node.node_id.slice(0, 6)}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <select
                className="rounded border border-slate-300 px-1 py-0.5"
                value={edgeKind}
                onChange={(event) => {
                  const next = event.target.value as "normal" | "error";
                  setEdgeKind(next);
                  if (next === "error") setEdgeCondition(null);
                }}
              >
                <option value="normal">normal</option>
                <option value="error">error</option>
              </select>
              <button type="button" onClick={onAddEdge} className="cursor-pointer rounded bg-blue-600 px-2 py-1 text-white">
                Edge 追加
              </button>
            </div>
            {edgeKind === "normal" && (
              <ConditionEditor
                idPrefix="edge-new"
                condition={edgeCondition}
                candidates={
                  edgeSource
                    ? conditionCandidates(nodes, edgeSource, inputsSchema)
                    : []
                }
                onChange={setEdgeCondition}
              />
            )}
          </section>

          <section className="space-y-2">
            <h3 className="font-semibold">入力 Schema</h3>
            <JsonArea
              label="inputs_schema"
              value={inputsSchema}
              onCommit={(value) => {
                setInputsSchema(value as Record<string, unknown>);
                markDirty();
              }}
            />
          </section>

          {selectedNode && (
            <section className="space-y-2 rounded border border-slate-200 p-2">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">
                  {selectedNode.node_type} 設定
                </h3>
                <button type="button" onClick={onDeleteNode} className="cursor-pointer rounded bg-rose-800 px-2 py-0.5 text-white">
                  削除
                </button>
              </div>
              {selectedNode.node_type === "capability" && (
                <>
                  <select
                    className="w-full rounded border border-slate-300 px-1 py-0.5"
                    value={String(selectedNode.config.capability_key ?? "")}
                    onChange={(event) =>
                      updateNodeConfig({ capability_key: event.target.value })
                    }
                  >
                    <option value="">capability を選択</option>
                    {capabilities
                      .filter((c) => c.enabled)
                      .map((c) => (
                        <option key={c.capability_key} value={c.capability_key}>
                          {c.capability_key}
                        </option>
                      ))}
                  </select>
                  <JsonArea
                    label="inputs"
                    value={selectedNode.config.inputs ?? {}}
                    onCommit={(value) => updateNodeConfig({ inputs: value })}
                  />
                </>
              )}
              {selectedNode.node_type === "agent" && (
                <>
                  <select
                    className="w-full rounded border border-slate-300 px-1 py-0.5"
                    value={String(selectedNode.config.agent_id ?? "")}
                    onChange={(event) =>
                      updateNodeConfig({ agent_id: event.target.value })
                    }
                  >
                    <option value="">Agent を選択</option>
                    {agents.map((agent) => (
                      <option key={agent.agent_id} value={agent.agent_id}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                  <JsonArea
                    label="inputs"
                    value={selectedNode.config.inputs ?? {}}
                    onCommit={(value) => updateNodeConfig({ inputs: value })}
                  />
                  <JsonArea
                    label="output_schema"
                    value={selectedNode.config.output_schema ?? {}}
                    onCommit={(value) => updateNodeConfig({ output_schema: value })}
                  />
                </>
              )}
              {selectedNode.node_type === "loop" && (
                <>
                  <JsonArea
                    label="state_schema"
                    value={selectedNode.config.state_schema ?? {}}
                    onCommit={(value) => updateNodeConfig({ state_schema: value })}
                  />
                  <JsonArea
                    label="input_mapping"
                    value={selectedNode.config.input_mapping ?? {}}
                    onCommit={(value) => updateNodeConfig({ input_mapping: value })}
                  />
                  <label className="block">
                    max_iterations
                    <input
                      type="number"
                      className="ml-1 w-20 rounded border border-slate-300 px-1"
                      value={Number(selectedNode.config.max_iterations ?? 1)}
                      onChange={(event) =>
                        updateNodeConfig({
                          max_iterations: Number(event.target.value),
                        })
                      }
                    />
                  </label>
                  <label className="block">
                    entry_node_id
                    <select
                      className="ml-1 rounded border border-slate-300 px-1"
                      value={String(selectedNode.config.entry_node_id ?? "")}
                      onChange={(event) =>
                        updateNodeConfig({ entry_node_id: event.target.value })
                      }
                    >
                      <option value="">選択</option>
                      {nodes
                        .filter(
                          (node) =>
                            node.parent_loop_node_id === selectedNode.node_id,
                        )
                        .map((node) => (
                          <option key={node.node_id} value={node.node_id}>
                            {node.node_id.slice(0, 6)}
                          </option>
                        ))}
                    </select>
                  </label>
                  <JsonArea
                    label="continuation_condition"
                    value={selectedNode.config.continuation_condition ?? {}}
                    onCommit={(value) =>
                      updateNodeConfig({ continuation_condition: value })
                    }
                  />
                </>
              )}
              {selectedNode.node_type === "loop_result" && (
                <JsonArea
                  label="output_mapping"
                  value={selectedNode.config.output_mapping ?? {}}
                  onCommit={(value) => updateNodeConfig({ output_mapping: value })}
                />
              )}
              {selectedNode.node_type === "terminal" && (
                <select
                  className="w-full rounded border border-slate-300 px-1 py-0.5"
                  value={String(selectedNode.config.outcome ?? "success")}
                  onChange={(event) =>
                    updateNodeConfig({ outcome: event.target.value })
                  }
                >
                  <option value="success">success</option>
                  <option value="failure">failure</option>
                </select>
              )}
            </section>
          )}

          <section className="space-y-2">
            <h3 className="font-semibold">Edge 一覧</h3>
            <ul className="space-y-1">
              {edges.map((edge) => (
                <li key={edge.edge_id} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="truncate">
                      {edge.source_node_id.slice(0, 5)}→{edge.target_node_id.slice(0, 5)}{" "}
                      ({edge.edge_kind}
                      {edge.condition ? ", cond" : ""})
                    </span>
                    <span className="flex gap-2">
                      {edge.edge_kind === "normal" && (
                        <button
                          type="button"
                          className="cursor-pointer text-blue-700"
                          onClick={() =>
                            setEditingEdgeId(
                              editingEdgeId === edge.edge_id
                                ? null
                                : edge.edge_id,
                            )
                          }
                        >
                          条件
                        </button>
                      )}
                      <button
                        type="button"
                        className="cursor-pointer text-rose-700"
                        onClick={() => {
                          setEdges((prev) =>
                            prev.filter((item) => item.edge_id !== edge.edge_id),
                          );
                          if (editingEdgeId === edge.edge_id) {
                            setEditingEdgeId(null);
                          }
                          markDirty();
                        }}
                      >
                        削除
                      </button>
                    </span>
                  </div>
                  {editingEdgeId === edge.edge_id && (
                    <ConditionEditor
                      idPrefix={`edge-${edge.edge_id}`}
                      condition={edge.condition}
                      candidates={conditionCandidates(
                        nodes,
                        edge.source_node_id,
                        inputsSchema,
                      )}
                      onChange={(condition) => {
                        setEdges((prev) =>
                          prev.map((item) =>
                            item.edge_id === edge.edge_id
                              ? { ...item, condition }
                              : item,
                          ),
                        );
                        markDirty();
                      }}
                    />
                  )}
                </li>
              ))}
            </ul>
          </section>

          <section className="space-y-2 rounded border border-slate-200 p-2">
            <h3 className="font-semibold">実行入力</h3>
            <InputsSchemaForm
              schema={inputsSchema}
              values={runInputs}
              onChange={setRunInputs}
              errors={runErrors}
            />
          </section>
        </aside>
      </div>
    </div>
  );
}

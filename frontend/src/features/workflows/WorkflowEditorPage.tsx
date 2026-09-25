import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
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
  WorkflowSchemaField,
} from "../../api/types";
import { workflowDetailPath, workflowRunPath } from "../../constants/routes";
import { getApiErrorMessage } from "../../utils/error";
import { revisionStatusLabel } from "./revisionLabels";
import ConditionEditor from "./ConditionEditor";
import InputsSchemaForm from "./InputsSchemaForm";
import SchemaAuthoringForm from "./SchemaAuthoringForm";
import StructuredValueEditor from "./StructuredValueEditor";
import TextTemplateEditor from "./TextTemplateEditor";
import TextTemplatePreview from "./TextTemplatePreview";
import WorkflowCanvas from "./WorkflowCanvas";
import { emptyObjectSchema } from "./schemaModel";
import {
  WORKFLOW_LLM_DEFAULT_MAX_TOKENS,
  WORKFLOW_LLM_PROVIDERS,
  WORKFLOW_LLM_REASONING_PROVIDERS,
  buildReferenceGroups,
  conditionCandidates,
  createNode,
  createEdge,
  defaultInputsSchema,
  moveNode,
  referenceSchemaAt,
  removeNode,
  runContextReferenceGroup,
  scopeOf,
  validateGraphShape,
  type GraphIssue,
  type ReferenceGroup,
} from "./graphModel";
import {
  buildSampleValues,
  templateVariables,
} from "./textTemplateModel";
import { useTextTemplatePreview } from "./useTextTemplatePreview";

const NODE_TYPE_LABELS: Record<WorkflowNodeType, string> = {
  capability: "capability",
  agent: "agent",
  llm: "単発 LLM (llm)",
  loop: "loop",
  text_template: "テキスト組立 (text_template)",
  terminal: "terminal",
  loop_result: "loop_result",
};

const NODE_TYPES = Object.keys(NODE_TYPE_LABELS) as WorkflowNodeType[];

function capabilityOptionSuffix(capability: WorkflowCapabilityRecord): string {
  const parts: string[] = [];
  if (!capability.read_only) parts.push("書込・外部");
  if (capability.approval_policy === "plan_required") parts.push("要承認");
  return parts.length > 0 ? ` (${parts.join("・")})` : "";
}

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
  const location = useLocation();
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
  const [serverIssues, setServerIssues] = useState<string[]>(
    () =>
      (location.state as { serverIssues?: string[] } | null)?.serverIssues ?? [],
  );
  const [serverWarnings, setServerWarnings] = useState<string[]>([]);
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
  const selectedCapability =
    selectedNode?.node_type === "capability"
      ? capabilities.find(
          (c) =>
            c.capability_key ===
            String(selectedNode.config.capability_key ?? ""),
        )
      : undefined;
  const targetSchemas = useMemo(() => {
    const map: Record<string, WorkflowSchemaField> = {};
    for (const capability of capabilities) {
      if (capability.target_schema) {
        map[capability.capability_key] = capability.target_schema;
      }
    }
    return map;
  }, [capabilities]);
  const capabilityOutputSchemas = useMemo(() => {
    const map: Record<string, WorkflowSchemaField> = {};
    for (const capability of capabilities) {
      if (capability.output_schema) {
        map[capability.capability_key] = capability.output_schema;
      }
    }
    return map;
  }, [capabilities]);
  const localIssues: GraphIssue[] = useMemo(
    () => validateGraphShape(nodes, edges, inputsSchema, targetSchemas),
    [nodes, edges, inputsSchema, targetSchemas],
  );

  const [textTemplateSamples, setTextTemplateSamples] = useState<
    Record<string, unknown>
  >({});
  const textTemplateConfig = (
    selectedNode?.node_type === "text_template" ? selectedNode.config : {}
  ) as Record<string, unknown>;
  const textTemplateInputs =
    (textTemplateConfig.inputs as Record<string, unknown>) ?? {};
  const textTemplateBody = String(textTemplateConfig.template ?? "");
  const textTemplateGroups =
    selectedNode?.node_type === "text_template"
      ? buildReferenceGroups(nodes, scopeOf(selectedNode), inputsSchema, {
          excludeNodeId: selectedNode.node_id,
          capabilityOutputSchemas,
        })
      : [];
  const textTemplateVariables = templateVariables(
    textTemplateInputs,
    textTemplateGroups,
  );
  const textTemplateSchemaFor = (name: string): WorkflowSchemaField | null => {
    const variable = textTemplateVariables.find((item) => item.name === name);
    if (!variable?.refPath || !selectedNode) return null;
    return referenceSchemaAt(nodes, variable.refPath, inputsSchema, {
      capabilityOutputSchemas,
      scopeId: scopeOf(selectedNode),
    });
  };
  const textTemplateVariableKey = textTemplateVariables
    .map(
      (variable) =>
        `${variable.name}:${variable.type ?? ""}:${variable.refPath ?? ""}`,
    )
    .join("\n");
  const scaffoldTextTemplateSamples = () =>
    buildSampleValues(textTemplateVariables, textTemplateInputs, (variable) =>
      textTemplateSchemaFor(variable.name),
    );
  useEffect(() => {
    // Sample values are editor-local (never persisted); reseed when the
    // selected node or its input variable set changes.
    setTextTemplateSamples(scaffoldTextTemplateSamples());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNodeId, textTemplateVariableKey]);
  const textTemplatePreview = useTextTemplatePreview(
    textTemplateBody,
    textTemplateSamples,
    { enabled: selectedNode?.node_type === "text_template" },
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
      setServerIssues([]);
      setServerWarnings([]);
      return true;
    } catch (e) {
      setError(getApiErrorMessage(e, "保存に失敗しました"));
      return false;
    }
  }, [revisionId, revision?.status, inputsSchema, nodes, edges]);

  const onValidate = async () => {
    setServerIssues([]);
    setServerWarnings([]);
    if (dirty && !(await save())) return;
    try {
      const res = await validateWorkflowRevision(revisionId);
      setServerIssues(res.errors);
      setServerWarnings(res.warnings ?? []);
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

  const groupsForNode = (nodeId: string): ReferenceGroup[] => {
    const node = nodes.find((item) => item.node_id === nodeId);
    return node
      ? buildReferenceGroups(nodes, scopeOf(node), inputsSchema, {
          capabilityOutputSchemas,
        })
      : [];
  };

  const pathsFromGroups = (groups: ReferenceGroup[]): string[] =>
    groups.flatMap((group) => group.fields.map((field) => field.path));

  const focusNode = (nodeId: string | undefined | null) => {
    if (!nodeId) return;
    setSelectedNodeId(nodeId);
    requestAnimationFrame(() => {
      document
        .querySelector(`[data-testid="workflow-node-${nodeId}"]`)
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  };

  const focusEdge = (edgeId: string) => {
    const edge = edges.find((item) => item.edge_id === edgeId);
    if (!edge) return;
    setEditingEdgeId(edgeId);
    focusNode(edge.source_node_id);
  };

  const serverIssueTarget = (
    text: string,
  ): { nodeId?: string; edgeId?: string } => {
    // Backend messages lead with the authoritative locator (``Node '<id>'`` or
    // ``edge '<id>'``) after an optional code prefix; a ``Node '...'`` later in
    // the body is the *referenced* node, not the offender.
    const nodeMatch = /Node '([^']+)'/.exec(text);
    const edgeMatch = /edge '([^']+)'/.exec(text);
    const nodeId = nodeMatch?.[1];
    const edgeId = edgeMatch?.[1];
    const nodeValid = nodeId && nodes.some((node) => node.node_id === nodeId);
    const edgeValid = edgeId && edges.some((edge) => edge.edge_id === edgeId);
    const edgeFirst = (edgeMatch?.index ?? Infinity) < (nodeMatch?.index ?? Infinity);
    if (edgeFirst && edgeValid) return { edgeId };
    if (nodeValid) return { nodeId };
    if (edgeValid) return { edgeId };
    return {};
  };

  const parentLoopStateSchema = selectedNode?.parent_loop_node_id
    ? ((nodes.find(
        (node) => node.node_id === selectedNode.parent_loop_node_id,
      )?.config as Record<string, unknown> | undefined)?.state_schema as
        | Record<string, unknown>
        | undefined)
    : undefined;

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

      {(error ||
        status ||
        localIssues.length > 0 ||
        serverIssues.length > 0 ||
        serverWarnings.length > 0) && (
        <div className="border-b border-slate-200 bg-white px-4 py-2 text-xs">
          {error && <p className="text-rose-700">{error}</p>}
          {status && <p className="text-slate-600">{status}</p>}
          {localIssues.length > 0 && (
            <ul data-testid="workflow-local-issues" className="text-amber-700">
              {localIssues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}>
                  {issue.nodeId || issue.edgeId ? (
                    <button
                      type="button"
                      className="cursor-pointer text-left underline decoration-dotted"
                      onClick={() => {
                        if (issue.edgeId) focusEdge(issue.edgeId);
                        focusNode(issue.nodeId);
                      }}
                    >
                      {issue.message}
                    </button>
                  ) : (
                    issue.message
                  )}
                </li>
              ))}
            </ul>
          )}
          {serverWarnings.length > 0 && (
            <ul data-testid="workflow-server-warnings" className="text-amber-700">
              {serverWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          {serverIssues.length > 0 && (
            <ul data-testid="workflow-server-issues" className="text-rose-700">
              {serverIssues.map((issue) => {
                const target = serverIssueTarget(issue);
                if (!target.nodeId && !target.edgeId) {
                  return <li key={issue}>{issue}</li>;
                }
                return (
                  <li key={issue}>
                    <button
                      type="button"
                      className="cursor-pointer text-left underline decoration-dotted"
                      onClick={() => {
                        if (target.edgeId) focusEdge(target.edgeId);
                        focusNode(target.nodeId);
                      }}
                    >
                      {issue}
                    </button>
                  </li>
                );
              })}
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
                    {NODE_TYPE_LABELS[type]}
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
                        {capabilityOptionSuffix(c)}
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
                groups={edgeSource ? groupsForNode(edgeSource) : []}
                onChange={setEdgeCondition}
              />
            )}
          </section>

          <section className="space-y-2">
            <h3 className="font-semibold">入力 Schema</h3>
            <SchemaAuthoringForm
              testIdPrefix="inputs-schema"
              schema={inputsSchema as WorkflowSchemaField}
              onChange={(value) => {
                setInputsSchema(value as Record<string, unknown>);
                markDirty();
              }}
            />
          </section>

          {selectedNode && (
            <section
              key={selectedNode.node_id}
              className="space-y-2 rounded border border-slate-200 p-2"
            >
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
                          {capabilityOptionSuffix(c)}
                        </option>
                      ))}
                  </select>
                  {selectedCapability?.description && (
                    <p className="text-[10px] leading-tight text-slate-500">
                      {selectedCapability.description}
                    </p>
                  )}
                  {selectedCapability && !selectedCapability.read_only && (
                    <p
                      data-testid="cap-write-warning"
                      className="text-[10px] leading-tight text-amber-700"
                    >
                      この Capability は書込・外部操作を含みます。
                    </p>
                  )}
                  {selectedCapability?.target_schema && (
                    <div className="space-y-1">
                      <span className="block text-slate-700">target</span>
                      <InputsSchemaForm
                        testIdPrefix="cap-target"
                        schema={selectedCapability.target_schema}
                        values={
                          (selectedNode.config.target as Record<
                            string,
                            unknown
                          >) ?? {}
                        }
                        onChange={(value) =>
                          updateNodeConfig({ target: value })
                        }
                      />
                    </div>
                  )}
                  {selectedCapability?.inputs_schema ? (
                    <div className="space-y-1">
                      <span className="block text-slate-700">inputs</span>
                      <InputsSchemaForm
                        testIdPrefix="cap-input"
                        schema={selectedCapability.inputs_schema}
                        values={
                          (selectedNode.config.inputs as Record<
                            string,
                            unknown
                          >) ?? {}
                        }
                        onChange={(value) => updateNodeConfig({ inputs: value })}
                        allowReferences
                        allowExpressions
                        referenceGroups={buildReferenceGroups(
                          nodes,
                          scopeOf(selectedNode),
                          inputsSchema,
                          {
                            excludeNodeId: selectedNode.node_id,
                            capabilityOutputSchemas,
                          },
                        )}
                      />
                    </div>
                  ) : (
                    <JsonArea
                      label="inputs"
                      value={selectedNode.config.inputs ?? {}}
                      onCommit={(value) => updateNodeConfig({ inputs: value })}
                    />
                  )}
                  <label className="block">
                    retry.max_attempts
                    <input
                      type="number"
                      min={0}
                      className="ml-1 w-20 rounded border border-slate-300 px-1"
                      value={Number(
                        (selectedNode.config.retry as { max_attempts?: number })
                          ?.max_attempts ?? 0,
                      )}
                      onChange={(event) =>
                        updateNodeConfig({
                          retry: {
                            ...((selectedNode.config.retry as Record<
                              string,
                              unknown
                            >) ?? {}),
                            max_attempts: Math.max(
                              0,
                              Number(event.target.value) || 0,
                            ),
                          },
                        })
                      }
                    />
                  </label>
                  <label className="flex items-center gap-1 text-slate-700">
                    <input
                      type="checkbox"
                      className="cursor-pointer"
                      data-testid="cap-fail-on-output-mismatch"
                      checked={
                        selectedNode.config.fail_on_output_mismatch === true
                      }
                      onChange={(event) =>
                        updateNodeConfig({
                          fail_on_output_mismatch: event.target.checked,
                        })
                      }
                    />
                    エラー出力・schema不一致で失敗
                  </label>
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
                  <div className="space-y-1">
                    <span className="block text-slate-700">inputs</span>
                    <StructuredValueEditor
                      testIdPrefix="agent-inputs"
                      value={
                        (selectedNode.config.inputs as Record<
                          string,
                          unknown
                        >) ?? {}
                      }
                      onChange={(value) => updateNodeConfig({ inputs: value })}
                      suggestions={["task", "context"]}
                      referenceGroups={buildReferenceGroups(
                        nodes,
                        scopeOf(selectedNode),
                        inputsSchema,
                        {
                          excludeNodeId: selectedNode.node_id,
                          capabilityOutputSchemas,
                        },
                      )}
                    />
                  </div>
                  <div className="space-y-1">
                    <span className="block text-slate-700">output_schema</span>
                    <SchemaAuthoringForm
                      testIdPrefix="agent-output-schema"
                      schema={
                        (selectedNode.config
                          .output_schema as WorkflowSchemaField) ??
                        emptyObjectSchema()
                      }
                      onChange={(value) =>
                        updateNodeConfig({ output_schema: value })
                      }
                    />
                  </div>
                </>
              )}
              {selectedNode.node_type === "llm" && (
                <>
                  <label className="block">
                    provider
                    <select
                      className="ml-1 rounded border border-slate-300 px-1"
                      value={String(selectedNode.config.provider ?? "openai")}
                      onChange={(event) => {
                        const provider = event.target.value;
                        const patch: Record<string, unknown> = { provider };
                        if (
                          !(
                            WORKFLOW_LLM_REASONING_PROVIDERS as readonly string[]
                          ).includes(provider)
                        ) {
                          patch.reasoning_effort = undefined;
                        }
                        updateNodeConfig(patch);
                      }}
                    >
                      {WORKFLOW_LLM_PROVIDERS.map((provider) => (
                        <option key={provider} value={provider}>
                          {provider}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    model
                    <input
                      type="text"
                      className="w-full rounded border border-slate-300 px-1"
                      value={String(selectedNode.config.model ?? "")}
                      onChange={(event) =>
                        updateNodeConfig({ model: event.target.value })
                      }
                      placeholder="例: gpt-5"
                    />
                  </label>
                  <label className="block">
                    system_prompt
                    <textarea
                      rows={4}
                      className="w-full rounded border border-slate-300 px-1 font-mono text-[11px]"
                      value={String(selectedNode.config.system_prompt ?? "")}
                      onChange={(event) =>
                        updateNodeConfig({ system_prompt: event.target.value })
                      }
                      placeholder="会話ではなく単発呼び出しの固定 system prompt"
                    />
                  </label>
                  <label className="block">
                    max_tokens
                    <input
                      type="number"
                      min={1}
                      className="ml-1 w-24 rounded border border-slate-300 px-1"
                      value={Number(
                        selectedNode.config.max_tokens ??
                          WORKFLOW_LLM_DEFAULT_MAX_TOKENS,
                      )}
                      onChange={(event) =>
                        updateNodeConfig({
                          max_tokens: Math.max(
                            1,
                            Number(event.target.value) || 1,
                          ),
                        })
                      }
                    />
                  </label>
                  {(
                    WORKFLOW_LLM_REASONING_PROVIDERS as readonly string[]
                  ).includes(String(selectedNode.config.provider ?? "")) && (
                    <>
                      <label className="block">
                        reasoning_effort
                        <input
                          type="text"
                          className="ml-1 rounded border border-slate-300 px-1"
                          value={String(
                            selectedNode.config.reasoning_effort ?? "",
                          )}
                          onChange={(event) =>
                            updateNodeConfig({
                              reasoning_effort:
                                event.target.value || undefined,
                            })
                          }
                          placeholder="例: low / medium / high（空欄で既定）"
                        />
                      </label>
                      <p className="text-[10px] text-slate-500">
                        reasoning_effort は openai / ollama / opencode_go でのみ
                        指定できます。
                      </p>
                    </>
                  )}
                  <div className="space-y-1">
                    <span className="block text-slate-700">inputs</span>
                    <StructuredValueEditor
                      testIdPrefix="llm-inputs"
                      value={
                        (selectedNode.config.inputs as Record<
                          string,
                          unknown
                        >) ?? {}
                      }
                      onChange={(value) => updateNodeConfig({ inputs: value })}
                      referenceGroups={buildReferenceGroups(
                        nodes,
                        scopeOf(selectedNode),
                        inputsSchema,
                        {
                          excludeNodeId: selectedNode.node_id,
                          capabilityOutputSchemas,
                        },
                      )}
                    />
                  </div>
                  <div className="space-y-1">
                    <span className="block text-slate-700">output_schema</span>
                    <SchemaAuthoringForm
                      testIdPrefix="llm-output-schema"
                      schema={
                        (selectedNode.config
                          .output_schema as WorkflowSchemaField) ??
                        emptyObjectSchema()
                      }
                      onChange={(value) =>
                        updateNodeConfig({ output_schema: value })
                      }
                    />
                  </div>
                </>
              )}
              {selectedNode.node_type === "loop" && (
                <>
                  <div className="space-y-1">
                    <span className="block text-slate-700">state_schema</span>
                    <SchemaAuthoringForm
                      testIdPrefix="loop-state-schema"
                      schema={
                        (selectedNode.config
                          .state_schema as WorkflowSchemaField) ??
                        emptyObjectSchema()
                      }
                      onChange={(value) =>
                        updateNodeConfig({ state_schema: value })
                      }
                    />
                  </div>
                  <div className="space-y-1">
                    <span className="block text-slate-700">input_mapping</span>
                    <InputsSchemaForm
                      testIdPrefix="loop-input-mapping"
                      schema={
                        (selectedNode.config.state_schema as Record<
                          string,
                          unknown
                        >) ?? {}
                      }
                      values={
                        (selectedNode.config.input_mapping as Record<
                          string,
                          unknown
                        >) ?? {}
                      }
                      onChange={(value) =>
                        updateNodeConfig({ input_mapping: value })
                      }
                      allowReferences
                      allowExpressions
                      referenceGroups={buildReferenceGroups(
                        nodes,
                        null,
                        inputsSchema,
                        { capabilityOutputSchemas },
                      )}
                    />
                  </div>
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
                  <div className="space-y-1">
                    <span className="block text-slate-700">
                      continuation_condition
                    </span>
                    <ConditionEditor
                      idPrefix={`loop-${selectedNode.node_id}`}
                      condition={
                        (selectedNode.config.continuation_condition as Record<
                          string,
                          unknown
                        > | null) ?? null
                      }
                      candidates={pathsFromGroups(
                        buildReferenceGroups(
                          nodes,
                          selectedNode.node_id,
                          inputsSchema,
                          { capabilityOutputSchemas },
                        ),
                      )}
                      groups={buildReferenceGroups(
                        nodes,
                        selectedNode.node_id,
                        inputsSchema,
                        { capabilityOutputSchemas },
                      )}
                      onChange={(condition) =>
                        updateNodeConfig({ continuation_condition: condition })
                      }
                    />
                  </div>
                </>
              )}
              {selectedNode.node_type === "loop_result" && (
                <div className="space-y-1">
                  <span className="block text-slate-700">output_mapping</span>
                  <InputsSchemaForm
                    testIdPrefix="loop-result-output-mapping"
                    schema={parentLoopStateSchema ?? {}}
                    values={
                      (selectedNode.config.output_mapping as Record<
                        string,
                        unknown
                      >) ?? {}
                    }
                    onChange={(value) =>
                      updateNodeConfig({ output_mapping: value })
                    }
                    allowReferences
                    allowExpressions
                    referenceGroups={buildReferenceGroups(
                      nodes,
                      selectedNode.parent_loop_node_id ?? null,
                      inputsSchema,
                      { capabilityOutputSchemas },
                    )}
                  />
                </div>
              )}
              {selectedNode.node_type === "text_template" && (
                <>
                  <div className="space-y-1">
                    <span className="block text-slate-700">inputs</span>
                    <StructuredValueEditor
                      testIdPrefix="text-template-inputs"
                      value={
                        (selectedNode.config.inputs as Record<
                          string,
                          unknown
                        >) ?? {}
                      }
                      onChange={(value) => updateNodeConfig({ inputs: value })}
                      referenceGroups={textTemplateGroups}
                    />
                  </div>
                  <TextTemplateEditor
                    value={textTemplateBody}
                    onChange={(template) => updateNodeConfig({ template })}
                    variables={textTemplateVariables}
                    schemaFor={textTemplateSchemaFor}
                  />
                  <TextTemplatePreview
                    preview={textTemplatePreview}
                    sampleValues={textTemplateSamples}
                    onChangeSampleValues={setTextTemplateSamples}
                    onGenerateScaffold={() =>
                      setTextTemplateSamples(scaffoldTextTemplateSamples())
                    }
                  />
                </>
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
                      groups={groupsForNode(edge.source_node_id)}
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
              allowExpressions
              allowNodeAnchors={false}
              expressionReferenceGroups={[runContextReferenceGroup()]}
            />
          </section>
        </aside>
      </div>
    </div>
  );
}

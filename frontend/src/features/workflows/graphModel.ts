import type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeType,
} from "../../api/types";

export type { WorkflowEdge, WorkflowNode, WorkflowNodeType };

export interface GraphIssue {
  code: string;
  message: string;
  nodeId?: string;
  edgeId?: string;
}

export function newNodeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `node-${Math.random().toString(36).slice(2, 10)}`;
}

export function newEdgeId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `edge-${Math.random().toString(36).slice(2, 10)}`;
}

export function defaultInputsSchema(): Record<string, unknown> {
  return { type: "object", properties: {} };
}

export function defaultNodeConfig(
  nodeType: WorkflowNodeType,
  capabilityKey?: string,
): Record<string, unknown> {
  switch (nodeType) {
    case "capability":
      return { capability_key: capabilityKey ?? "", inputs: {} };
    case "agent":
      return {
        agent_id: "",
        inputs: {},
        output_schema: { type: "object", properties: {} },
      };
    case "loop":
      return {
        state_schema: { type: "object", properties: {} },
        input_mapping: {},
        continuation_condition: {
          from_path: "loop.state.done",
          operator: "equals",
          value: true,
        },
        max_iterations: 5,
        entry_node_id: "",
      };
    case "loop_result":
      return { output_mapping: {} };
    case "terminal":
      return { outcome: "success" };
    default:
      return {};
  }
}

export function createNode(
  nodeType: WorkflowNodeType,
  position: { x: number; y: number },
  capabilityKey?: string,
  parentLoopNodeId?: string | null,
): WorkflowNode {
  return {
    node_id: newNodeId(),
    node_type: nodeType,
    label: null,
    config: defaultNodeConfig(nodeType, capabilityKey),
    parent_loop_node_id: parentLoopNodeId ?? null,
    ui_position: position,
  };
}

export function createEdge(
  sourceNodeId: string,
  targetNodeId: string,
  orderIndex: number,
): WorkflowEdge {
  return {
    edge_id: newEdgeId(),
    source_node_id: sourceNodeId,
    target_node_id: targetNodeId,
    edge_kind: "normal",
    condition: null,
    order_index: orderIndex,
  };
}

export function moveNode(
  nodes: WorkflowNode[],
  nodeId: string,
  position: { x: number; y: number },
): WorkflowNode[] {
  return nodes.map((node) =>
    node.node_id === nodeId ? { ...node, ui_position: position } : node,
  );
}

export function removeNode(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  nodeId: string,
): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
  const removed = new Set<string>([nodeId]);
  // Removing a Loop Node also removes its child graph (and its edges).
  for (const node of nodes) {
    if (node.parent_loop_node_id === nodeId) removed.add(node.node_id);
  }
  return {
    nodes: nodes.filter((node) => !removed.has(node.node_id)),
    edges: edges.filter(
      (edge) =>
        !removed.has(edge.source_node_id) && !removed.has(edge.target_node_id),
    ),
  };
}

export function scopeOf(node: WorkflowNode): string | null {
  return node.parent_loop_node_id ?? null;
}

export interface ReferenceScope {
  inputsKeys?: string[];
  nodeIds?: string[];
  inLoop?: boolean;
}

const REFERENCE_PATTERN = /^([a-z]+)\.([^.]*)(?:\.(.*))?$/;

export function validateReference(
  ref: string,
  scope: ReferenceScope,
): GraphIssue | null {
  const match = REFERENCE_PATTERN.exec(ref);
  if (!match) {
    return { code: "reference_scope", message: `未対応の参照形式: ${ref}` };
  }
  const [head, second, rest] = [match[1], match[2], match[3]];
  if (head === "run" && second === "inputs") {
    const field = (rest ?? "").split(".")[0].replace(/\[\d+\]$/, "");
    if (scope.inputsKeys && field && !scope.inputsKeys.includes(field)) {
      return {
        code: "reference_scope",
        message: `run.inputs.${field} は inputs_schema にありません`,
      };
    }
    return null;
  }
  if (head === "nodes") {
    if (rest === undefined || !rest.startsWith("output")) {
      return {
        code: "reference_scope",
        message: `nodes 参照は nodes.<id>.output.* の形式が必要です: ${ref}`,
      };
    }
    if (scope.nodeIds && !scope.nodeIds.includes(second)) {
      return {
        code: "reference_scope",
        message: `参照先 Node '${second}' は同一スコープにありません`,
      };
    }
    return null;
  }
  if (head === "loop") {
    if (!["state", "input", "iteration"].includes(second)) {
      return { code: "reference_scope", message: `未対応の loop 参照: ${ref}` };
    }
    if (!scope.inLoop) {
      return {
        code: "reference_scope",
        message: `loop.* 参照は Loop 子グラフ内でのみ使えます: ${ref}`,
      };
    }
    return null;
  }
  return { code: "reference_scope", message: `未対応の参照: ${ref}` };
}

export function collectReferences(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((child) => collectReferences(child));
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record);
    if (keys.length === 1 && keys[0] === "$ref") {
      return typeof record.$ref === "string" ? [record.$ref] : [];
    }
    return Object.values(record).flatMap((child) => collectReferences(child));
  }
  return [];
}

export function inputsKeysFromSchema(
  schema: Record<string, unknown> | undefined,
): string[] {
  const properties = schema?.properties;
  if (properties && typeof properties === "object") {
    return Object.keys(properties as Record<string, unknown>);
  }
  return [];
}

export const CONDITION_OPERATORS = ["equals", "exists", "in"] as const;
export type ConditionOperator = (typeof CONDITION_OPERATORS)[number];

/** Candidate reference paths usable as a condition's ``from_path``. */
export function conditionCandidates(
  nodes: WorkflowNode[],
  sourceNodeId: string,
  inputsSchema: Record<string, unknown>,
): string[] {
  const source = nodes.find((node) => node.node_id === sourceNodeId);
  if (!source) return [];
  const scope = scopeOf(source);
  const scopeIds = nodes
    .filter((node) => scopeOf(node) === scope)
    .map((node) => node.node_id);
  const candidates: string[] = inputsKeysFromSchema(inputsSchema).map(
    (key) => `run.inputs.${key}`,
  );
  for (const nodeId of scopeIds) {
    candidates.push(`nodes.${nodeId}.output`);
  }
  if (scope !== null) {
    const loop = nodes.find((node) => node.node_id === scope);
    const stateSchema = (loop?.config as Record<string, unknown> | undefined)
      ?.state_schema as Record<string, unknown> | undefined;
    const stateProps = (stateSchema?.properties ?? {}) as Record<string, unknown>;
    for (const key of Object.keys(stateProps)) {
      candidates.push(`loop.state.${key}`);
    }
    const inputMapping = (loop?.config as Record<string, unknown> | undefined)
      ?.input_mapping as Record<string, unknown> | undefined;
    for (const key of Object.keys(inputMapping ?? {})) {
      candidates.push(`loop.input.${key}`);
    }
    candidates.push("loop.iteration");
  }
  return candidates;
}

/** Validate the shape of one condition object (mirrors backend validation). */
export function validateConditionShape(
  condition: unknown,
  path = "condition",
): GraphIssue[] {
  if (!condition || typeof condition !== "object") {
    return [{ code: "condition_shape", message: `${path} は object が必要です` }];
  }
  const record = condition as Record<string, unknown>;
  const issues: GraphIssue[] = [];
  if (typeof record.from_path !== "string" || !record.from_path.trim()) {
    issues.push({
      code: "condition_from_path",
      message: `${path}.from_path が必要です`,
    });
  }
  const operator = record.operator;
  if (!CONDITION_OPERATORS.includes(operator as ConditionOperator)) {
    issues.push({
      code: "condition_operator",
      message: `${path}.operator が不正です`,
    });
  }
  if (
    (operator === "equals" || operator === "in") &&
    !("value" in record)
  ) {
    issues.push({
      code: "condition_value",
      message: `${path}.value が必要です`,
    });
  }
  if (operator === "in" && "value" in record && !Array.isArray(record.value)) {
    issues.push({
      code: "condition_value_array",
      message: `${path}.value は配列が必要です`,
    });
  }
  return issues;
}

/** Parse the text input for a condition value. ``in`` requires a JSON array. */
export function parseConditionValue(
  raw: string,
  operator: ConditionOperator,
): { ok: true; value: unknown } | { ok: false; error: string } {
  if (operator === "in") {
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) {
        return { ok: false, error: "JSON 配列を入力してください" };
      }
      return { ok: true, value: parsed };
    } catch {
      return { ok: false, error: "JSON 配列として解釈できません" };
    }
  }
  const trimmed = raw.trim();
  if (trimmed === "") return { ok: true, value: "" };
  try {
    return { ok: true, value: JSON.parse(trimmed) };
  } catch {
    return { ok: true, value: raw };
  }
}

/** Client-side structural checks that mirror the backend validator codes. */
export function validateGraphShape(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  inputsSchema: Record<string, unknown>,
): GraphIssue[] {
  const issues: GraphIssue[] = [];
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const scopes = new Map<string | null, WorkflowNode[]>();
  for (const node of nodes) {
    const scope = scopeOf(node);
    scopes.set(scope, [...(scopes.get(scope) ?? []), node]);
  }

  for (const node of nodes) {
    const config = (node.config ?? {}) as Record<string, unknown>;
    if (node.node_type === "capability" && !config.capability_key) {
      issues.push({
        code: "capability_key_required",
        message: "capability_key が必要です",
        nodeId: node.node_id,
      });
    }
    if (node.node_type === "agent" && !config.agent_id) {
      issues.push({
        code: "agent_id_required",
        message: "agent_id が必要です",
        nodeId: node.node_id,
      });
    }
    if (node.node_type === "loop" && scopeOf(node) !== null) {
      issues.push({
        code: "loop_nested",
        message: "Loop Node のネストは未対応です",
        nodeId: node.node_id,
      });
    }
    if (node.node_type === "loop_result" && scopeOf(node) === null) {
      issues.push({
        code: "loop_scope",
        message: "loop_result は Loop 子グラフ内でのみ使えます",
        nodeId: node.node_id,
      });
    }
  }

  // Terminal nodes must have no outgoing edge, and conditions must be valid.
  for (const edge of edges) {
    const source = byId.get(edge.source_node_id);
    if (source?.node_type === "terminal") {
      issues.push({
        code: "terminal_outgoing",
        message: "terminal Node に outgoing Edge があります",
        edgeId: edge.edge_id,
      });
    }
    if (edge.condition) {
      const shapeIssues = validateConditionShape(edge.condition);
      for (const issue of shapeIssues) {
        issues.push({ ...issue, edgeId: edge.edge_id });
      }
      // Resolve references only when the shape is valid (backend parity).
      if (shapeIssues.length === 0) {
        const scope = source ? scopeOf(source) : null;
        const scopeIds = (scopes.get(scope) ?? []).map((node) => node.node_id);
        const error = validateReference(String(edge.condition.from_path ?? ""), {
          inputsKeys: inputsKeysFromSchema(inputsSchema),
          nodeIds: scopeIds,
          inLoop: scope !== null,
        });
        if (error) issues.push({ ...error, edgeId: edge.edge_id });
      }
    }
  }

  // Each scope needs exactly one entry node and must be acyclic.
  for (const [scope, scopeNodes] of scopes) {
    const ids = new Set(scopeNodes.map((node) => node.node_id));
    const scopeEdges = edges.filter(
      (edge) => ids.has(edge.source_node_id) && ids.has(edge.target_node_id),
    );
    const incoming = new Map<string, number>();
    ids.forEach((id) => incoming.set(id, 0));
    for (const edge of scopeEdges) {
      incoming.set(
        edge.target_node_id,
        (incoming.get(edge.target_node_id) ?? 0) + 1,
      );
    }
    if (scope === null) {
      const entries = [...ids].filter((id) => (incoming.get(id) ?? 0) === 0);
      if (entries.length !== 1) {
        issues.push({
          code: "entry_count",
          message: `entry Node は 1 つ必要です（現在 ${entries.length} 個）`,
        });
      }
    }
    if (hasCycle(ids, scopeEdges)) {
      issues.push({ code: "cycle", message: "グラフに循環 Edge があります" });
    }
  }

  const inputsKeys = inputsKeysFromSchema(inputsSchema);
  for (const node of nodes) {
    const scope = scopeOf(node);
    const scopeIds = (scopes.get(scope) ?? []).map((n) => n.node_id);
    const references = [
      ...collectReferences((node.config as Record<string, unknown>).inputs),
      ...collectReferences(
        (node.config as Record<string, unknown>).input_mapping,
      ),
      ...collectReferences(
        (node.config as Record<string, unknown>).output_mapping,
      ),
    ];
    for (const ref of references) {
      const issue = validateReference(ref, {
        inputsKeys,
        nodeIds: scopeIds,
        inLoop: scope !== null,
      });
      if (issue) issues.push({ ...issue, nodeId: node.node_id });
    }
  }
  return issues;
}

function hasCycle(ids: Set<string>, edges: WorkflowEdge[]): boolean {
  const adjacency = new Map<string, string[]>();
  ids.forEach((id) => adjacency.set(id, []));
  for (const edge of edges) {
    adjacency.get(edge.source_node_id)?.push(edge.target_node_id);
  }
  const state = new Map<string, number>();
  const visit = (id: string): boolean => {
    const current = state.get(id) ?? 0;
    if (current === 1) return true;
    if (current === 2) return false;
    state.set(id, 1);
    for (const next of adjacency.get(id) ?? []) {
      if (visit(next)) return true;
    }
    state.set(id, 2);
    return false;
  };
  return [...ids].some((id) => visit(id));
}

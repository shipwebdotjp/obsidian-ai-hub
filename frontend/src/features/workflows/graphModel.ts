import type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowPipeOp,
  WorkflowReferenceValue,
  WorkflowSchemaField,
} from "../../api/types";
import { validatePipe } from "./pipeModel";

export type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeType,
  WorkflowPipeOp,
  WorkflowReferenceValue,
};

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

/** Providers accepted by the backend ``llm`` node (mirrors llm_node.py). */
export const WORKFLOW_LLM_PROVIDERS = [
  "openai",
  "gemini",
  "ollama",
  "local",
  "opencode_go",
] as const;

/** Providers that accept ``reasoning_effort`` (mirrors llm_node.py). */
export const WORKFLOW_LLM_REASONING_PROVIDERS = [
  "openai",
  "ollama",
  "opencode_go",
] as const;

/** Config keys accepted by the backend ``llm`` node (mirrors llm_node.py). */
export const WORKFLOW_LLM_CONFIG_KEYS = [
  "provider",
  "model",
  "system_prompt",
  "max_tokens",
  "reasoning_effort",
  "inputs",
  "output_schema",
] as const;

export const WORKFLOW_LLM_DEFAULT_MAX_TOKENS = 4096;

export function defaultNodeConfig(
  nodeType: WorkflowNodeType,
  capabilityKey?: string,
): Record<string, unknown> {
  switch (nodeType) {
    case "capability":
      return { capability_key: capabilityKey ?? "", target: {}, inputs: {} };
    case "agent":
      return {
        agent_id: "",
        inputs: {},
        output_schema: { type: "object", properties: {} },
      };
    case "llm":
      return {
        provider: "openai",
        model: "",
        system_prompt: "",
        max_tokens: WORKFLOW_LLM_DEFAULT_MAX_TOKENS,
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
    case "text_template":
      return { inputs: {}, template: "" };
    default:
      return {};
  }
}

/** Display name for a graph node: label first, then type-specific config. */
export function nodeDisplayName(node: WorkflowNode): string {
  const label = typeof node.label === "string" ? node.label.trim() : "";
  if (label) return label;
  const config = (node.config ?? {}) as Record<string, unknown>;
  for (const key of ["capability_key", "agent_id", "model", "outcome"] as const) {
    const value = config[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return node.node_type;
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
  if (head === "run" && second === "context") {
    if (ref === REFERENCE_TIME_REF) return null;
    return {
      code: "reference_scope",
      message: `未対応の run.context 参照: ${ref}`,
    };
  }
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

interface ReferenceEntry {
  path: string;
  pipe: WorkflowPipeOp[];
}

/** One recursive walk over a nested value yielding every reference entry. */
function collectReferenceEntries(value: unknown): ReferenceEntry[] {
  if (Array.isArray(value)) {
    return value.flatMap(collectReferenceEntries);
  }
  if (value && typeof value === "object") {
    const path = referencePath(value);
    if (path !== null) return [{ path, pipe: referencePipe(value) }];
    const record = value as Record<string, unknown>;
    return Object.values(record).flatMap(collectReferenceEntries);
  }
  return [];
}

/** Collect every resolvable reference path (skips the empty editor sentinel). */
export function collectReferences(value: unknown): string[] {
  return collectReferenceEntries(value)
    .map((entry) => entry.path)
    .filter((path) => path !== "");
}

/** Collect every non-empty pipe op list attached to a reference. */
export function collectPipes(value: unknown): WorkflowPipeOp[][] {
  return collectReferenceEntries(value)
    .map((entry) => entry.pipe)
    .filter((pipe) => pipe.length > 0);
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

export interface ReferenceField {
  path: string;
  type?: string;
  description?: string;
}

export interface ReferenceGroup {
  label: string;
  fields: ReferenceField[];
}

function asSchemaField(schema: unknown): WorkflowSchemaField | null {
  return schema && typeof schema === "object"
    ? (schema as WorkflowSchemaField)
    : null;
}

/** True for ``{"$ref": "<path>"}`` with an optional ``pipe`` array. */
export function isReferenceValue(
  value: unknown,
): value is WorkflowReferenceValue {
  return referencePath(value) !== null;
}

/** Return the ``$ref`` path of a bare/piped reference, else ``null``.

An empty string is a valid in-progress sentinel (the editor enters reference
mode with ``{ $ref: "" }``); callers that resolve paths must skip it.
*/
export function referencePath(value: unknown): string | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (!keys.includes("$ref") || keys.some((key) => key !== "$ref" && key !== "pipe")) {
    return null;
  }
  if (typeof record.$ref !== "string") return null;
  if ("pipe" in record && !Array.isArray(record.pipe)) return null;
  return record.$ref;
}

/** Return the pipe ops of a reference value (empty when none). */
export function referencePipe(value: unknown): WorkflowPipeOp[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  const pipe = (value as { pipe?: unknown }).pipe;
  return Array.isArray(pipe) ? (pipe as WorkflowPipeOp[]) : [];
}

/** Set the ``$ref`` path, preserving an existing non-empty pipe. */
export function setReferencePath(
  value: unknown,
  path: string,
): WorkflowReferenceValue {
  const pipe = referencePipe(value);
  return pipe.length ? { $ref: path, pipe } : { $ref: path };
}

/** Set the pipe, dropping it when empty; preserves the current ``$ref``. */
export function setReferencePipe(
  value: unknown,
  pipe: WorkflowPipeOp[],
): WorkflowReferenceValue {
  const ref = referencePath(value) ?? "";
  return pipe.length ? { $ref: ref, pipe } : { $ref: ref };
}

/**
 * Flatten a normalized schema into selectable reference paths.
 *
 * Objects expose both the whole-object path and their (recursive) children so a
 * node can pass a full object or one field. Arrays stay a single field; item
 * indices are intentionally not enumerated.
 */
export function schemaReferenceFields(
  schema: unknown,
  basePath: string,
): ReferenceField[] {
  const field = asSchemaField(schema);
  if (!field || field["x-unsupported"]) {
    return [{ path: basePath, type: "object" }];
  }
  const description = field.description;
  if (field.type === "object" && field.properties) {
    return [
      { path: basePath, type: "object", description },
      ...Object.entries(field.properties).flatMap(([name, sub]) =>
        schemaReferenceFields(sub, `${basePath}.${name}`),
      ),
    ];
  }
  if (field.type === "array") {
    const fields: ReferenceField[] = [
      { path: basePath, type: "array", description },
    ];
    const items = asSchemaField(field.items);
    // Offer an indexed example so the ``[N]`` syntax is discoverable, but only
    // for arrays nested below a property: the backend only accepts an index
    // after a field segment, not on a container path (``nodes.x.output[0]``).
    const nestedArray =
      basePath !== "run.inputs" &&
      basePath !== "loop.state" &&
      basePath !== "loop.input" &&
      !basePath.endsWith(".output");
    if (
      nestedArray &&
      items &&
      !items["x-unsupported"] &&
      items.type &&
      items.type !== "object" &&
      items.type !== "array"
    ) {
      fields.push({ path: `${basePath}[0]`, type: items.type });
    }
    return fields;
  }
  if (field.enum) {
    return [{ path: basePath, type: "enum", description }];
  }
  return [{ path: basePath, type: field.type ?? "object", description }];
}

const REFERENCE_PATH_RE =
  /^(?:run\.inputs\..+|run\.context\.reference_time|nodes\.[^.]+\.output(?:\..+)?|loop\.(?:state|input)(?:\..+)?|loop\.iteration)$/;

/** Grammar-only check: true when ``value`` is a resolvable reference shape. */
export function isReferencePath(value: string): boolean {
  return REFERENCE_PATH_RE.test(value.trim());
}

function nodeOutputFields(
  node: WorkflowNode,
  nodes: WorkflowNode[],
  capabilityOutputSchemas?: Record<string, WorkflowSchemaField>,
): ReferenceField[] {
  const config = (node.config ?? {}) as Record<string, unknown>;
  const basePath = `nodes.${node.node_id}.output`;
  if (node.node_type === "agent" || node.node_type === "llm") {
    return schemaReferenceFields(config.output_schema, basePath);
  }
  if (node.node_type === "loop") {
    return [
      { path: basePath, type: "object" },
      ...schemaReferenceFields(config.state_schema, `${basePath}.final_state`),
      { path: `${basePath}.iterations`, type: "integer" },
      { path: `${basePath}.exit_reason`, type: "string" },
    ];
  }
  if (node.node_type === "loop_result") {
    const parent = nodes.find(
      (candidate) => candidate.node_id === node.parent_loop_node_id,
    );
    const stateSchema = (parent?.config as Record<string, unknown> | undefined)
      ?.state_schema;
    return schemaReferenceFields(stateSchema, basePath);
  }
  if (node.node_type === "capability") {
    const key = String(config.capability_key ?? "");
    const outputSchema = capabilityOutputSchemas?.[key];
    if (outputSchema) {
      return schemaReferenceFields(outputSchema, basePath);
    }
    return [
      {
        path: basePath,
        type: "object",
        description:
          "Capability 出力は型未宣言（summary、または JSON object 全体）。",
      },
    ];
  }
  if (node.node_type === "text_template") {
    return [
      {
        path: `${basePath}.text`,
        type: "string",
        description: "組立済みのテキスト",
      },
    ];
  }
  return [{ path: basePath, type: "object" }];
}

/**
 * Resolve the JSON schema declared at a typed reference path, else ``null``.
 *
 * Used by the ``text_template`` editor to offer nested field completion (e.g.
 * ``event.title`` inside a ``{% for %}``). Only the schema shapes the editor can
 * already express are resolved; opaque capability outputs yield ``null``.
 */
export function referenceSchemaAt(
  nodes: WorkflowNode[],
  path: string,
  inputsSchema: Record<string, unknown>,
  options: {
    capabilityOutputSchemas?: Record<string, WorkflowSchemaField>;
    scopeId?: string | null;
  } = {},
): WorkflowSchemaField | null {
  const trimmed = path.trim();
  if (trimmed === REFERENCE_TIME_REF) return { type: "string" };
  if (trimmed === "loop.iteration") return { type: "integer" };

  const nodeMatch = /^nodes\.([^.]+)\.output(\..*)?$/.exec(trimmed);
  if (nodeMatch) {
    const node = nodes.find((item) => item.node_id === nodeMatch[1]);
    if (!node) return null;
    return walkSchemaPath(
      nodeOutputSchema(node, nodes, options.capabilityOutputSchemas),
      nodeMatch[2] ?? "",
    );
  }
  if (trimmed === "run.inputs" || trimmed.startsWith("run.inputs.")) {
    return walkSchemaPath(
      asSchemaField(inputsSchema),
      trimmed.slice("run.inputs".length),
    );
  }
  if (trimmed === "loop.state" || trimmed.startsWith("loop.state.")) {
    const loop = options.scopeId
      ? nodes.find((item) => item.node_id === options.scopeId)
      : undefined;
    const stateSchema = asSchemaField(
      (loop?.config as Record<string, unknown> | undefined)?.state_schema,
    );
    return walkSchemaPath(stateSchema, trimmed.slice("loop.state".length));
  }
  return null;
}

function nodeOutputSchema(
  node: WorkflowNode,
  nodes: WorkflowNode[],
  capabilityOutputSchemas?: Record<string, WorkflowSchemaField>,
): WorkflowSchemaField | null {
  const config = (node.config ?? {}) as Record<string, unknown>;
  if (node.node_type === "agent" || node.node_type === "llm") {
    return asSchemaField(config.output_schema);
  }
  if (node.node_type === "loop") {
    return {
      type: "object",
      properties: {
        final_state: asSchemaField(config.state_schema) ?? {},
        iterations: { type: "integer" },
        exit_reason: { type: "string" },
      },
    };
  }
  if (node.node_type === "loop_result") {
    const parent = nodes.find(
      (candidate) => candidate.node_id === node.parent_loop_node_id,
    );
    const stateSchema = (parent?.config as Record<string, unknown> | undefined)
      ?.state_schema;
    return asSchemaField(stateSchema);
  }
  if (node.node_type === "capability") {
    const key = String(config.capability_key ?? "");
    return capabilityOutputSchemas?.[key] ?? null;
  }
  if (node.node_type === "text_template") {
    return { type: "object", properties: { text: { type: "string" } } };
  }
  return null;
}

function walkSchemaPath(
  schema: WorkflowSchemaField | null,
  subPath: string,
): WorkflowSchemaField | null {
  if (!schema) return null;
  const segments = subPath.replace(/^\./, "").split(".").filter(Boolean);
  let current: WorkflowSchemaField | null = schema;
  for (const segment of segments) {
    if (!current) return null;
    const [name] = segment.split("[");
    if (name) {
      const property: WorkflowSchemaField | undefined =
        current.properties?.[name];
      if (property) {
        current = property;
      } else if (
        current.additionalProperties &&
        typeof current.additionalProperties === "object"
      ) {
        current = current.additionalProperties;
      } else {
        return null;
      }
    }
    if (segment.includes("[")) {
      const container: WorkflowSchemaField | null = current;
      current =
        container && container.type === "array"
          ? container.items ?? null
          : null;
    }
  }
  return current;
}

/** The frozen reference-time path shared by validation and the editor. */
export const REFERENCE_TIME_REF = "run.context.reference_time";

/** The single source for the ``run.context`` reference candidate group. */
export function runContextReferenceGroup(): ReferenceGroup {
  return {
    label: "実行コンテキスト (run.context)",
    fields: [
      {
        path: REFERENCE_TIME_REF,
        type: "string",
        description: "Run 作成時に固定された基準時刻（date-time）",
      },
    ],
  };
}

/**
 * Build the typed reference candidates available inside a scope.
 *
 * ``scopeId`` is ``null`` for the top level or the owning Loop Node id for a
 * child graph. ``excludeNodeId`` hides a node's own output (used when editing
 * that node's inputs).
 */
export function buildReferenceGroups(
  nodes: WorkflowNode[],
  scopeId: string | null,
  inputsSchema: Record<string, unknown>,
  options: {
    excludeNodeId?: string;
    capabilityOutputSchemas?: Record<string, WorkflowSchemaField>;
  } = {},
): ReferenceGroup[] {
  const groups: ReferenceGroup[] = [];
  // A bare ``run.inputs`` is not resolvable at runtime (the backend requires
  // ``run.inputs.<field>``), so the container path itself is not offered.
  const inputFields = schemaReferenceFields(inputsSchema, "run.inputs").filter(
    (field) => field.path !== "run.inputs",
  );
  if (inputFields.length > 0) {
    groups.push({ label: "実行入力 (run.inputs)", fields: inputFields });
  }
  groups.push(runContextReferenceGroup());

  const scopeNodes = nodes.filter(
    (node) =>
      scopeOf(node) === scopeId && node.node_id !== options.excludeNodeId,
  );
  for (const node of scopeNodes) {
    groups.push({
      label: `${nodeDisplayName(node)} (${node.node_id.slice(0, 6)})`,
      fields: nodeOutputFields(node, nodes, options.capabilityOutputSchemas),
    });
  }

  if (scopeId !== null) {
    const loop = nodes.find((node) => node.node_id === scopeId);
    const loopConfig = (loop?.config ?? {}) as Record<string, unknown>;
    const fields: ReferenceField[] = [
      ...schemaReferenceFields(loopConfig.state_schema, "loop.state"),
    ];
    const inputMapping = (loopConfig.input_mapping ?? {}) as Record<
      string,
      unknown
    >;
    for (const key of Object.keys(inputMapping)) {
      fields.push({ path: `loop.input.${key}` });
    }
    fields.push({ path: "loop.iteration", type: "integer" });
    groups.push({ label: "Loop 状態", fields });
  }
  return groups;
}

/** Candidate reference paths usable as a condition's ``from_path``. */
export function conditionCandidates(
  nodes: WorkflowNode[],
  sourceNodeId: string,
  inputsSchema: Record<string, unknown>,
): string[] {
  const source = nodes.find((node) => node.node_id === sourceNodeId);
  if (!source) return [];
  return buildReferenceGroups(nodes, scopeOf(source), inputsSchema).flatMap(
    (group) => group.fields.map((field) => field.path),
  );
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
  targetSchemas?: Record<string, WorkflowSchemaField>,
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
    if (node.node_type === "capability" && config.capability_key) {
      const targetSchema = targetSchemas?.[String(config.capability_key)];
      if (targetSchema) {
        const target = config.target;
        if (
          !target ||
          typeof target !== "object" ||
          Array.isArray(target)
        ) {
          issues.push({
            code: "capability_target_required",
            message: "target が必要です",
            nodeId: node.node_id,
          });
        } else {
          const targetRecord = target as Record<string, unknown>;
          const required = Array.isArray(targetSchema.required)
            ? targetSchema.required
            : [];
          for (const name of required) {
            const value = targetRecord[name];
            if (value === undefined || value === null || value === "") {
              issues.push({
                code: "capability_target_required",
                message: `target.${name} が必要です`,
                nodeId: node.node_id,
              });
            }
          }
        }
      }
    }
    if (node.node_type === "agent" && !config.agent_id) {
      issues.push({
        code: "agent_id_required",
        message: "agent_id が必要です",
        nodeId: node.node_id,
      });
    }
    if (node.node_type === "llm") {
      const provider = String(config.provider ?? "");
      const unknownKeys = Object.keys(config).filter(
        (key) => !(WORKFLOW_LLM_CONFIG_KEYS as readonly string[]).includes(key),
      );
      if (unknownKeys.length > 0) {
        issues.push({
          code: "llm_unknown_keys",
          message: `llm の未知キー: ${unknownKeys.join(", ")}`,
          nodeId: node.node_id,
        });
      }
      if (!(WORKFLOW_LLM_PROVIDERS as readonly string[]).includes(provider)) {
        issues.push({
          code: "llm_provider",
          message: "llm.provider が不正です",
          nodeId: node.node_id,
        });
      }
      if (typeof config.model !== "string" || !config.model.trim()) {
        issues.push({
          code: "llm_model",
          message: "llm.model が必要です",
          nodeId: node.node_id,
        });
      }
      if (typeof config.system_prompt !== "string") {
        issues.push({
          code: "llm_system_prompt",
          message: "llm.system_prompt は文字列が必要です",
          nodeId: node.node_id,
        });
      }
      const maxTokens = config.max_tokens;
      if (
        typeof maxTokens !== "number" ||
        !Number.isInteger(maxTokens) ||
        maxTokens < 1
      ) {
        issues.push({
          code: "llm_max_tokens",
          message: "llm.max_tokens は正整数が必要です",
          nodeId: node.node_id,
        });
      }
      const effort = config.reasoning_effort;
      if (effort !== undefined && effort !== null && effort !== "") {
        if (typeof effort !== "string" || !effort.trim()) {
          issues.push({
            code: "llm_reasoning_effort",
            message: "llm.reasoning_effort は空でない文字列が必要です",
            nodeId: node.node_id,
          });
        } else if (
          !(WORKFLOW_LLM_REASONING_PROVIDERS as readonly string[]).includes(
            provider,
          )
        ) {
          issues.push({
            code: "llm_reasoning_effort",
            message: `llm.reasoning_effort は provider '${provider}' では使えません`,
            nodeId: node.node_id,
          });
        }
      }
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
    if (node.node_type === "text_template") {
      const inputs = config.inputs;
      if (
        inputs !== undefined &&
        (inputs === null || typeof inputs !== "object" || Array.isArray(inputs))
      ) {
        issues.push({
          code: "text_template_inputs",
          message: "text_template.inputs は object が必要です",
          nodeId: node.node_id,
        });
      }
      if (typeof config.template !== "string") {
        issues.push({
          code: "text_template_template",
          message: "text_template.template は文字列が必要です",
          nodeId: node.node_id,
        });
      }
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
    const pipes = [
      ...collectPipes((node.config as Record<string, unknown>).inputs),
      ...collectPipes((node.config as Record<string, unknown>).input_mapping),
      ...collectPipes((node.config as Record<string, unknown>).output_mapping),
    ];
    for (const pipe of pipes) {
      for (const issue of validatePipe(pipe)) {
        issues.push({ ...issue, nodeId: node.node_id });
      }
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

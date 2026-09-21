import { describe, expect, it } from "vitest";
import {
  conditionCandidates,
  createEdge,
  createNode,
  defaultNodeConfig,
  parseConditionValue,
  removeNode,
  validateGraphShape,
  type WorkflowEdge,
  type WorkflowNode,
} from "./graphModel";

function node(
  id: string,
  type: WorkflowNode["node_type"],
  config: Record<string, unknown>,
  parent: string | null = null,
): WorkflowNode {
  return {
    node_id: id,
    node_type: type,
    config,
    parent_loop_node_id: parent,
    ui_position: { x: 0, y: 0 },
  };
}

function edge(id: string, source: string, target: string): WorkflowEdge {
  return {
    edge_id: id,
    source_node_id: source,
    target_node_id: target,
    edge_kind: "normal",
    condition: null,
    order_index: 0,
  };
}

const capability = (key = "vault_search") => ({
  capability_key: key,
  inputs: {},
});

describe("graphModel", () => {
  it("creates nodes with type-specific defaults", () => {
    const node = createNode("capability", { x: 10, y: 20 }, "vault_search");
    expect(node.node_type).toBe("capability");
    expect(node.config.capability_key).toBe("vault_search");
    expect(node.ui_position).toEqual({ x: 10, y: 20 });
    expect(Number(defaultNodeConfig("loop").max_iterations)).toBeGreaterThan(0);
    expect(defaultNodeConfig("terminal").outcome).toBe("success");
  });

  it("removes loop children together with the loop node", () => {
    const nodes = [
      node("loop", "loop", defaultNodeConfig("loop")),
      node("child", "capability", capability(), "loop"),
      node("end", "terminal", { outcome: "success" }),
    ];
    const edges = [edge("e1", "loop", "end")];
    const result = removeNode(nodes, edges, "loop");
    expect(result.nodes.map((n) => n.node_id)).toEqual(["end"]);
    expect(result.edges).toHaveLength(0);
  });

  it("reports a missing entry node", () => {
    const nodes = [
      node("a", "capability", capability()),
      node("b", "capability", capability()),
      node("end", "terminal", { outcome: "success" }),
    ];
    const edges = [edge("e1", "a", "end"), edge("e2", "b", "end")];
    const issues = validateGraphShape(nodes, edges, { type: "object" });
    expect(issues.some((issue) => issue.code === "entry_count")).toBe(true);
  });

  it("detects a cycle", () => {
    const nodes = [
      node("a", "capability", capability()),
      node("b", "capability", capability()),
    ];
    const edges = [edge("e1", "a", "b"), edge("e2", "b", "a")];
    const issues = validateGraphShape(nodes, edges, { type: "object" });
    expect(issues.some((issue) => issue.code === "cycle")).toBe(true);
  });

  it("requires capability and agent targets", () => {
    const nodes = [
      node("a", "capability", { inputs: {} }),
      node("agent", "agent", { inputs: {} }),
    ];
    const issues = validateGraphShape(nodes, [], { type: "object" });
    expect(issues.some((issue) => issue.code === "capability_key_required")).toBe(
      true,
    );
    expect(issues.some((issue) => issue.code === "agent_id_required")).toBe(true);
  });

  it("validates reference scope and accepts indexed run inputs", () => {
    const nodes = [
      node("a", "capability", {
        capability_key: "vault_search",
        inputs: { q: { $ref: "run.inputs.items[0]" } },
      }),
      node("bad", "capability", {
        capability_key: "vault_search",
        inputs: { q: { $ref: "nodes.missing.output.x" } },
      }),
    ];
    const issues = validateGraphShape(nodes, [], {
      type: "object",
      properties: { items: { type: "array", items: { type: "string" } } },
    });
    const referenceIssues = issues.filter(
      (issue) => issue.code === "reference_scope",
    );
    expect(referenceIssues).toHaveLength(1);
    expect(referenceIssues[0].nodeId).toBe("bad");
  });
});


describe("condition helpers", () => {
  const schema = {
    type: "object",
    properties: { flag: { type: "boolean" } },
  };

  it("lists run.inputs, node outputs and loop state candidates", () => {
    const loop = node("loop", "loop", {
      ...defaultNodeConfig("loop"),
      state_schema: {
        type: "object",
        properties: { done: { type: "boolean" } },
      },
      input_mapping: { draft: "" },
    });
    const child = node("child", "capability", capability(), "loop");
    const end = node("end", "terminal", { outcome: "success" });
    const top = node("top", "capability", capability());

    const topCandidates = conditionCandidates([top, end], "top", schema);
    expect(topCandidates).toContain("run.inputs.flag");
    expect(topCandidates).toContain("nodes.end.output");
    expect(topCandidates).not.toContain("loop.iteration");

    const loopCandidates = conditionCandidates([loop, child, end], "child", schema);
    expect(loopCandidates).toContain("loop.state.done");
    expect(loopCandidates).toContain("loop.input.draft");
    expect(loopCandidates).toContain("loop.iteration");
  });

  it("flags malformed conditions with backend parity", () => {
    const nodes = [node("a", "capability", capability()), node("end", "terminal", { outcome: "success" })];
    const base = edge("e1", "a", "end");

    const badOperator = validateGraphShape(
      nodes,
      [{ ...base, condition: { from_path: "run.inputs.flag", operator: "nope" } }],
      schema,
    ).map((issue) => issue.code);
    expect(badOperator).toContain("condition_operator");
    expect(badOperator).not.toContain("condition_value");

    const missingValue = validateGraphShape(
      nodes,
      [{ ...base, condition: { from_path: "run.inputs.flag", operator: "equals" } }],
      schema,
    ).map((issue) => issue.code);
    expect(missingValue).toContain("condition_value");
    expect(missingValue).not.toContain("reference_scope");

    // Shape-valid condition with a broken reference still reports scope.
    const badReference = validateGraphShape(
      nodes,
      [
        {
          ...base,
          condition: { from_path: "nodes.missing.output.x", operator: "equals", value: 1 },
        },
      ],
      schema,
    ).map((issue) => issue.code);
    expect(badReference).toContain("reference_scope");
  });

  it("requires an array for the in operator", () => {
    const nodes = [node("a", "capability", capability()), node("end", "terminal", { outcome: "success" })];
    const edges: WorkflowEdge[] = [
      {
        ...edge("e1", "a", "end"),
        condition: { from_path: "run.inputs.flag", operator: "in", value: "x" },
      },
    ];
    const codes = validateGraphShape(nodes, edges, schema).map((i) => i.code);
    expect(codes).toContain("condition_value_array");
  });

  it("parses condition values by operator", () => {
    expect(parseConditionValue("true", "equals")).toEqual({ ok: true, value: true });
    expect(parseConditionValue("hello", "equals")).toEqual({ ok: true, value: "hello" });
    expect(parseConditionValue("[1,2]", "in")).toEqual({ ok: true, value: [1, 2] });
    expect(parseConditionValue("oops", "in").ok).toBe(false);
  });
});

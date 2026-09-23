import { describe, expect, it } from "vitest";
import {
  buildReferenceGroups,
  collectReferences,
  defaultNodeConfig,
  isReferenceValue,
  referencePath,
  referencePipe,
  setReferencePath,
  setReferencePipe,
  validateGraphShape,
} from "./graphModel";
import type { WorkflowEdge, WorkflowNode } from "../../api/types";

function node(
  node_id: string,
  node_type: WorkflowNode["node_type"],
  config: Record<string, unknown>,
): WorkflowNode {
  return {
    node_id,
    node_type,
    label: null,
    config,
    parent_loop_node_id: null,
    ui_position: null,
  };
}

describe("reference pipe shape", () => {
  it("recognizes piped references", () => {
    const value = { $ref: "run.inputs.x", pipe: [{ op: "upper" }] };
    expect(isReferenceValue(value)).toBe(true);
    expect(referencePath(value)).toBe("run.inputs.x");
    expect(referencePipe(value)).toEqual([{ op: "upper" }]);
    expect(referencePath({ $ref: "a", other: 1 })).toBeNull();
    expect(referencePath({ $ref: "a", pipe: "x" })).toBeNull();
  });

  it("keeps the empty-$ref editor sentinel but skips it in collection", () => {
    expect(isReferenceValue({ $ref: "" })).toBe(true);
    expect(collectReferences({ q: { $ref: "" } })).toEqual([]);
    expect(collectReferences({ q: { $ref: "run.inputs.q" } })).toEqual([
      "run.inputs.q",
    ]);
  });

  it("sets path/pipe without dropping the other", () => {
    const piped = { $ref: "a", pipe: [{ op: "upper" }] };
    expect(setReferencePath(piped, "b")).toEqual({
      $ref: "b",
      pipe: [{ op: "upper" }],
    });
    expect(setReferencePipe({ $ref: "a" }, [{ op: "upper" }])).toEqual({
      $ref: "a",
      pipe: [{ op: "upper" }],
    });
    expect(setReferencePipe(piped, [])).toEqual({ $ref: "a" });
  });
});

describe("text_template node model", () => {
  it("has a default config and exposes output.text", () => {
    expect(defaultNodeConfig("text_template")).toEqual({
      inputs: {},
      template: "",
    });
    const nodes = [node("tt", "text_template", { inputs: {}, template: "x" })];
    const groups = buildReferenceGroups(nodes, null, {
      type: "object",
      properties: {},
    });
    const paths = groups.flatMap((group) => group.fields.map((f) => f.path));
    expect(paths).toContain("nodes.tt.output.text");
  });

  it("flags invalid config and pipe errors", () => {
    const badNodes = [
      node("tt", "text_template", { inputs: [], template: 3 }),
      node("t", "terminal", { outcome: "success" }),
    ];
    const edges: WorkflowEdge[] = [
      {
        edge_id: "e1",
        source_node_id: "tt",
        target_node_id: "t",
        edge_kind: "normal",
        condition: null,
        order_index: 0,
      },
    ];
    const issues = validateGraphShape(badNodes, edges, {
      type: "object",
      properties: {},
    });
    expect(issues.some((i) => i.code === "text_template_inputs")).toBe(true);
    expect(issues.some((i) => i.code === "text_template_template")).toBe(true);

    const pipeNode = node("tt2", "text_template", {
      inputs: { q: { $ref: "run.inputs.q", pipe: [{ op: "bogus" }] } },
      template: "{{ q }}",
    });
    const pipeEdges: WorkflowEdge[] = [
      {
        edge_id: "e2",
        source_node_id: "tt2",
        target_node_id: "t",
        edge_kind: "normal",
        condition: null,
        order_index: 0,
      },
    ];
    const pipeIssues = validateGraphShape(
      [pipeNode, node("t", "terminal", { outcome: "success" })],
      pipeEdges,
      { type: "object", properties: { q: { type: "string" } } },
    );
    expect(pipeIssues.some((i) => i.code === "pipe_op")).toBe(true);
  });
});

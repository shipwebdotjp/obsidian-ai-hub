import { describe, expect, it } from "vitest";
import type { WorkflowNode, WorkflowRunNode } from "../../api/types";
import { nodeDisplayName } from "./graphModel";
import {
  aggregateNodeStates,
  historyForNode,
  initialSelectedNodeId,
  layoutRunGraph,
  runGraphOf,
  RUN_GRAPH_NODE_HEIGHT,
  RUN_GRAPH_NODE_WIDTH,
} from "./runGraphModel";

function graphNode(
  id: string,
  type: WorkflowNode["node_type"] = "capability",
  config: Record<string, unknown> = {},
  overrides: Partial<WorkflowNode> = {},
): WorkflowNode {
  return {
    node_id: id,
    node_type: type,
    label: null,
    config,
    parent_loop_node_id: null,
    ui_position: null,
    ...overrides,
  };
}

function runRow(
  nodeId: string,
  activationId: string,
  attempt: number,
  status: WorkflowRunNode["status"],
  startedAt: string,
): WorkflowRunNode {
  return {
    run_id: "wrun_1",
    node_id: nodeId,
    activation_id: activationId,
    attempt,
    status,
    started_at: startedAt,
    finished_at: null,
  };
}

describe("nodeDisplayName", () => {
  it("prefers the label over type-specific config", () => {
    expect(
      nodeDisplayName(
        graphNode("a", "capability", { capability_key: "vault_search" }, { label: "検索" }),
      ),
    ).toBe("検索");
  });

  it("falls back to capability key, agent id, outcome, then node type", () => {
    expect(
      nodeDisplayName(graphNode("a", "capability", { capability_key: "vault_search" })),
    ).toBe("vault_search");
    expect(
      nodeDisplayName(graphNode("a", "agent", { agent_id: "agent_1" })),
    ).toBe("agent_1");
    expect(
      nodeDisplayName(graphNode("a", "terminal", { outcome: "failure" })),
    ).toBe("failure");
    expect(nodeDisplayName(graphNode("a", "loop", {}))).toBe("loop");
  });

  it("ignores blank labels and config values", () => {
    expect(
      nodeDisplayName(
        graphNode("a", "capability", { capability_key: "  " }, { label: "  " }),
      ),
    ).toBe("capability");
  });
});

describe("runGraphOf", () => {
  it("returns null when the snapshot is missing or empty", () => {
    expect(runGraphOf({ run_id: "wrun_1" } as never)).toBeNull();
    expect(
      runGraphOf({
        run_id: "wrun_1",
        graph_snapshot: {},
      } as never),
    ).toBeNull();
    expect(
      runGraphOf({
        run_id: "wrun_1",
        graph_snapshot: { nodes: [], edges: [] },
      } as never),
    ).toBeNull();
  });

  it("returns typed nodes and edges from the snapshot", () => {
    const nodes = [graphNode("a")];
    const edges = [
      {
        edge_id: "e1",
        source_node_id: "a",
        target_node_id: "b",
        edge_kind: "normal" as const,
        condition: null,
        order_index: 0,
      },
    ];
    expect(
      runGraphOf({ run_id: "wrun_1", graph_snapshot: { nodes, edges } } as never),
    ).toEqual({ nodes, edges });
  });
});

describe("aggregateNodeStates", () => {
  it("takes the last attempt of one activation", () => {
    const states = aggregateNodeStates([
      runRow("a", "act_1", 1, "failed", "2026-09-21T00:00:01Z"),
      runRow("a", "act_1", 2, "succeeded", "2026-09-21T00:00:02Z"),
    ]);
    expect(states.get("a")).toEqual({
      status: "succeeded",
      activationCount: 1,
      latestAttempt: 2,
    });
  });

  it("counts loop activations and reports the latest one", () => {
    const states = aggregateNodeStates([
      runRow("child", "act_1", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("child", "act_2", 1, "running", "2026-09-21T00:00:02Z"),
    ]);
    expect(states.get("child")).toEqual({
      status: "running",
      activationCount: 2,
      latestAttempt: 1,
    });
  });

  it("prefers a newer succeeded activation over an older needs_attention one", () => {
    const states = aggregateNodeStates([
      runRow("a", "act_1", 1, "needs_attention", "2026-09-21T00:00:01Z"),
      runRow("a", "act_2", 1, "succeeded", "2026-09-21T00:00:02Z"),
    ]);
    expect(states.get("a")?.status).toBe("succeeded");
    expect(states.get("a")?.activationCount).toBe(2);
  });

  it("keeps an unresolved needs_attention as the node status", () => {
    const states = aggregateNodeStates([
      runRow("a", "act_1", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("b", "act_2", 1, "needs_attention", "2026-09-21T00:00:02Z"),
    ]);
    expect(states.get("b")?.status).toBe("needs_attention");
  });
});

describe("layoutRunGraph", () => {
  it("keeps snapshot coordinates and grows the canvas when needed", () => {
    const layout = layoutRunGraph([
      graphNode("a", "capability", {}, { ui_position: { x: 1200, y: 40 } }),
    ]);
    expect(layout.positions.a).toEqual({ x: 1200, y: 40 });
    expect(layout.width).toBeGreaterThanOrEqual(1200 + RUN_GRAPH_NODE_WIDTH);
    expect(layout.height).toBe(560);
  });

  it("places nodes without coordinates on non-overlapping grid cells", () => {
    const nodes = [
      graphNode("placed", "capability", {}, { ui_position: { x: 24, y: 24 } }),
      graphNode("missing_1"),
      graphNode("missing_2"),
      graphNode("missing_3"),
    ];
    const layout = layoutRunGraph(nodes);
    const boxes = Object.values(layout.positions);
    expect(boxes).toHaveLength(4);
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const first = boxes[i];
        const second = boxes[j];
        const separated =
          first.x + RUN_GRAPH_NODE_WIDTH <= second.x ||
          second.x + RUN_GRAPH_NODE_WIDTH <= first.x ||
          first.y + RUN_GRAPH_NODE_HEIGHT <= second.y ||
          second.y + RUN_GRAPH_NODE_HEIGHT <= first.y;
        expect(separated).toBe(true);
      }
    }
  });

  it("treats negative coordinates like missing ones", () => {
    const layout = layoutRunGraph([
      graphNode("placed", "capability", {}, { ui_position: { x: 24, y: 24 } }),
      graphNode("negative", "capability", {}, { ui_position: { x: -10, y: -5 } }),
    ]);
    expect(layout.positions.placed).toEqual({ x: 24, y: 24 });
    expect(layout.positions.negative).not.toEqual({ x: 0, y: 0 });
    expect(layout.positions.negative.x).toBeGreaterThanOrEqual(0);
    expect(layout.positions.negative.y).toBeGreaterThanOrEqual(0);
  });

  it("handles an empty graph with the default canvas size", () => {
    expect(layoutRunGraph([])).toEqual({
      positions: {},
      width: 960,
      height: 560,
    });
  });
});

describe("initialSelectedNodeId", () => {
  const ids = ["a", "b", "c"];
  it("prefers needs_attention, then running, then the last executed node", () => {
    const states = aggregateNodeStates([
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("b", "act_b", 1, "running", "2026-09-21T00:00:02Z"),
    ]);
    expect(initialSelectedNodeId(ids, [
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("b", "act_b", 1, "running", "2026-09-21T00:00:02Z"),
    ], states)).toBe("b");

    const attentionStates = aggregateNodeStates([
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("b", "act_b", 1, "needs_attention", "2026-09-21T00:00:02Z"),
    ]);
    expect(initialSelectedNodeId(ids, [
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("b", "act_b", 1, "needs_attention", "2026-09-21T00:00:02Z"),
    ], attentionStates)).toBe("b");
  });

  it("falls back to the last executed node, or null when nothing ran", () => {
    const states = aggregateNodeStates([
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("c", "act_c", 1, "failed", "2026-09-21T00:00:02Z"),
    ]);
    expect(initialSelectedNodeId(ids, [
      runRow("a", "act_a", 1, "succeeded", "2026-09-21T00:00:01Z"),
      runRow("c", "act_c", 1, "failed", "2026-09-21T00:00:02Z"),
    ], states)).toBe("c");
    expect(initialSelectedNodeId(ids, [], new Map())).toBeNull();
  });

  it("ignores run rows for nodes missing from the graph", () => {
    const states = aggregateNodeStates([
      runRow("gone", "act_g", 1, "running", "2026-09-21T00:00:01Z"),
    ]);
    expect(initialSelectedNodeId(ids, [
      runRow("gone", "act_g", 1, "running", "2026-09-21T00:00:01Z"),
    ], states)).toBeNull();
  });
});

describe("historyForNode", () => {
  it("returns only rows of the selected node in order", () => {
    const rows = [
      runRow("a", "act_a", 1, "failed", "2026-09-21T00:00:01Z"),
      runRow("b", "act_b", 1, "succeeded", "2026-09-21T00:00:02Z"),
      runRow("a", "act_a", 2, "succeeded", "2026-09-21T00:00:03Z"),
    ];
    expect(historyForNode(rows, "a")).toEqual([rows[0], rows[2]]);
  });
});

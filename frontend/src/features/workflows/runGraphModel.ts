import type {
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeStatus,
  WorkflowRun,
  WorkflowRunNode,
} from "../../api/types";

/** Aggregated state of one graph node. `unexecuted` means no run row exists. */
export type RunGraphNodeStatus = WorkflowNodeStatus | "unexecuted";

export interface RunGraphNodeState {
  status: RunGraphNodeStatus;
  /** Distinct activation count (Loop iterations / reexecutions). */
  activationCount: number;
  /** Highest attempt of the latest activation. */
  latestAttempt: number;
}

/** Japanese display labels for aggregated node states. */
export const RUN_GRAPH_STATUS_LABELS: Record<RunGraphNodeStatus, string> = {
  needs_attention: "対応待ち",
  running: "実行中",
  waiting_hitl: "回答待ち",
  succeeded: "成功",
  failed: "失敗",
  cancelled: "取消",
  skipped: "スキップ",
  pending: "待機",
  unexecuted: "未実行",
};

export interface RunGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

/** Graph from the run's snapshot, or null when the run predates snapshots. */
export function runGraphOf(run: WorkflowRun): RunGraph | null {
  const nodes = Array.isArray(run.graph_snapshot?.nodes)
    ? run.graph_snapshot.nodes
    : [];
  if (nodes.length === 0) return null;
  return { nodes, edges: run.graph_snapshot?.edges ?? [] };
}

/**
 * Aggregate run rows per graph node.
 *
 * ``list_run_nodes`` comes ordered by ``started_at`` ascending, so the last
 * row of a node is the latest attempt of its latest activation. ISO
 * timestamps also compare lexicographically, so unordered input is handled.
 */
export function aggregateNodeStates(
  runNodes: WorkflowRunNode[],
): Map<string, RunGraphNodeState> {
  const latest = new Map<string, WorkflowRunNode>();
  const activations = new Map<string, Set<string>>();
  const attempts = new Map<string, Map<string, number>>();
  for (const row of runNodes ?? []) {
    const previous = latest.get(row.node_id);
    if (!previous || (row.started_at ?? "") >= (previous.started_at ?? "")) {
      latest.set(row.node_id, row);
    }
    let activationIds = activations.get(row.node_id);
    if (!activationIds) {
      activationIds = new Set();
      activations.set(row.node_id, activationIds);
    }
    activationIds.add(row.activation_id);
    let perActivation = attempts.get(row.node_id);
    if (!perActivation) {
      perActivation = new Map();
      attempts.set(row.node_id, perActivation);
    }
    perActivation.set(
      row.activation_id,
      Math.max(perActivation.get(row.activation_id) ?? 0, row.attempt),
    );
  }
  const states = new Map<string, RunGraphNodeState>();
  for (const [nodeId, row] of latest) {
    states.set(nodeId, {
      status: row.status,
      activationCount: activations.get(nodeId)?.size ?? 0,
      latestAttempt: attempts.get(nodeId)?.get(row.activation_id) ?? row.attempt,
    });
  }
  return states;
}

export const RUN_GRAPH_NODE_WIDTH = 180;
export const RUN_GRAPH_NODE_HEIGHT = 64;

export interface RunGraphLayout {
  positions: Record<string, { x: number; y: number }>;
  width: number;
  height: number;
}

const GRID_ORIGIN = 24;
const GRID_CELL_WIDTH = 220;
const GRID_CELL_HEIGHT = 120;
const GRID_COLUMNS = 4;
const MIN_CANVAS_WIDTH = 960;
const MIN_CANVAS_HEIGHT = 560;

interface Point {
  x: number;
  y: number;
}

function overlaps(first: Point, second: Point, padding: number): boolean {
  return (
    first.x < second.x + RUN_GRAPH_NODE_WIDTH + padding &&
    second.x < first.x + RUN_GRAPH_NODE_WIDTH + padding &&
    first.y < second.y + RUN_GRAPH_NODE_HEIGHT + padding &&
    second.y < first.y + RUN_GRAPH_NODE_HEIGHT + padding
  );
}

/**
 * Positions for the run graph. Nodes with a valid snapshot coordinate keep
 * it; nodes without one (or with a negative one) fall into non-overlapping
 * grid cells. The canvas size grows past the default when positions exceed
 * it.
 */
export function layoutRunGraph(nodes: WorkflowNode[]): RunGraphLayout {
  const positions: Record<string, Point> = {};
  const occupied: Point[] = [];
  for (const node of nodes) {
    const stored = node.ui_position;
    if (
      stored &&
      Number.isFinite(stored.x) &&
      Number.isFinite(stored.y) &&
      stored.x >= 0 &&
      stored.y >= 0
    ) {
      const point = { x: stored.x, y: stored.y };
      positions[node.node_id] = point;
      occupied.push(point);
    }
  }
  let cell = 0;
  for (const node of nodes) {
    if (positions[node.node_id]) continue;
    // Grid cells never overlap each other; skip cells colliding with
    // explicitly positioned nodes so missing coordinates stay visible.
    for (;;) {
      const point = {
        x: GRID_ORIGIN + (cell % GRID_COLUMNS) * GRID_CELL_WIDTH,
        y: GRID_ORIGIN + Math.floor(cell / GRID_COLUMNS) * GRID_CELL_HEIGHT,
      };
      cell += 1;
      if (!occupied.some((other) => overlaps(other, point, 8))) {
        positions[node.node_id] = point;
        occupied.push(point);
        break;
      }
    }
  }
  let maxX = 0;
  let maxY = 0;
  for (const point of Object.values(positions)) {
    maxX = Math.max(maxX, point.x + RUN_GRAPH_NODE_WIDTH);
    maxY = Math.max(maxY, point.y + RUN_GRAPH_NODE_HEIGHT);
  }
  return {
    positions,
    width: Math.max(MIN_CANVAS_WIDTH, maxX + GRID_ORIGIN),
    height: Math.max(MIN_CANVAS_HEIGHT, maxY + GRID_ORIGIN),
  };
}

/**
 * Default node selection: a node needing attention, then a running/waiting
 * node, then the most recently executed node. Null when nothing ran yet.
 */
export function initialSelectedNodeId(
  graphNodeIds: string[],
  runNodes: WorkflowRunNode[],
  states: Map<string, RunGraphNodeState>,
): string | null {
  const inGraph = new Set(graphNodeIds);
  const findByStatus = (
    wanted: readonly RunGraphNodeStatus[],
  ): string | null => {
    for (const row of runNodes ?? []) {
      const status = states.get(row.node_id)?.status;
      if (
        status !== undefined &&
        wanted.includes(status) &&
        inGraph.has(row.node_id)
      ) {
        return row.node_id;
      }
    }
    return null;
  };
  return (
    findByStatus(["needs_attention"]) ??
    findByStatus(["running", "waiting_hitl"]) ??
    [...(runNodes ?? [])].reverse().find((row) => inGraph.has(row.node_id))
      ?.node_id ??
    null
  );
}

/** All run rows (every activation and attempt) for one graph node. */
export function historyForNode(
  runNodes: WorkflowRunNode[],
  nodeId: string,
): WorkflowRunNode[] {
  return (runNodes ?? []).filter((row) => row.node_id === nodeId);
}

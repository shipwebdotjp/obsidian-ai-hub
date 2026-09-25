import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { WorkflowEdge, WorkflowNode } from "../../api/types";
import { nodeDisplayName, scopeOf } from "./graphModel";
import {
  RUN_GRAPH_NODE_HEIGHT,
  RUN_GRAPH_NODE_WIDTH,
  RUN_GRAPH_STATUS_LABELS,
  type RunGraphNodeState,
} from "./runGraphModel";

const NODE_WIDTH = RUN_GRAPH_NODE_WIDTH;
const NODE_HEIGHT = RUN_GRAPH_NODE_HEIGHT;
const DEFAULT_CANVAS_WIDTH = 960;
const DEFAULT_CANVAS_HEIGHT = 560;

export interface WorkflowCanvasProps {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  onMoveNode?: (nodeId: string, position: { x: number; y: number }) => void;
  /** Read-only run view: selection only, no dragging, status display. */
  readOnly?: boolean;
  /** Aggregated run state per node id. Absent nodes render unexecuted. */
  nodeStates?: Record<string, RunGraphNodeState>;
  /** Override node positions (e.g. grid fallback for missing coordinates). */
  positions?: Record<string, { x: number; y: number }>;
  canvasWidth?: number;
  canvasHeight?: number;
}

const RUN_STATUS_STYLE: Record<
  RunGraphNodeState["status"],
  { box: string; badge: string }
> = {
  needs_attention: { box: "border-amber-500 bg-amber-50", badge: "bg-amber-600 text-white" },
  running: { box: "border-blue-500 bg-blue-50", badge: "bg-blue-600 text-white" },
  waiting_hitl: { box: "border-blue-500 bg-blue-50", badge: "bg-blue-600 text-white" },
  succeeded: { box: "border-emerald-500 bg-emerald-50", badge: "bg-emerald-600 text-white" },
  failed: { box: "border-rose-500 bg-rose-50", badge: "bg-rose-600 text-white" },
  cancelled: { box: "border-slate-500 bg-slate-100", badge: "bg-slate-600 text-white" },
  skipped: { box: "border-slate-300 bg-slate-50", badge: "bg-slate-400 text-white" },
  pending: { box: "border-slate-300 bg-white", badge: "bg-slate-400 text-white" },
  unexecuted: { box: "", badge: "" },
};

function nodeTypeClass(nodeType: WorkflowNode["node_type"]): string {
  switch (nodeType) {
    case "capability":
      return "border-blue-400 bg-blue-50";
    case "agent":
      return "border-purple-400 bg-purple-50";
    case "llm":
      return "border-emerald-400 bg-emerald-50";
    case "loop":
      return "border-amber-400 bg-amber-50";
    case "loop_result":
      return "border-teal-400 bg-teal-50";
    case "terminal":
      return "border-slate-400 bg-slate-100";
    default:
      return "border-slate-300 bg-white";
  }
}

export default function WorkflowCanvas({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  onMoveNode,
  readOnly = false,
  nodeStates,
  positions,
  canvasWidth = DEFAULT_CANVAS_WIDTH,
  canvasHeight = DEFAULT_CANVAS_HEIGHT,
}: WorkflowCanvasProps) {
  const [drag, setDrag] = useState<{ nodeId: string; dx: number; dy: number } | null>(
    null,
  );
  const containerRef = useRef<HTMLDivElement>(null);

  const positionOf = (node: WorkflowNode): { x: number; y: number } =>
    positions?.[node.node_id] ?? node.ui_position ?? { x: 40, y: 40 };

  const startDrag = (
    event: ReactPointerEvent<HTMLDivElement>,
    node: WorkflowNode,
  ) => {
    onSelectNode(node.node_id);
    if (!onMoveNode) return;
    const position = positionOf(node);
    const rect = containerRef.current?.getBoundingClientRect();
    setDrag({
      nodeId: node.node_id,
      dx: event.clientX - (rect?.left ?? 0) - position.x,
      dy: event.clientY - (rect?.top ?? 0) - position.y,
    });
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.max(0, Math.min(canvasWidth - NODE_WIDTH, event.clientX - rect.left - drag.dx));
    const y = Math.max(0, Math.min(canvasHeight - NODE_HEIGHT, event.clientY - rect.top - drag.dy));
    onMoveNode?.(drag.nodeId, { x, y });
  };

  const endDrag = () => setDrag(null);

  const centerOf = (node: WorkflowNode) => {
    const position = positionOf(node);
    return { x: position.x + NODE_WIDTH / 2, y: position.y + NODE_HEIGHT / 2 };
  };

  const draggable = !readOnly && onMoveNode !== undefined;

  return (
    <div
      ref={containerRef}
      data-testid="workflow-canvas"
      className="relative overflow-auto rounded border border-slate-200 bg-slate-50"
      style={{ width: "100%", height: canvasHeight }}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
    >
      <div style={{ width: canvasWidth, height: canvasHeight, position: "relative" }}>
        <svg
          width={canvasWidth}
          height={canvasHeight}
          className="absolute inset-0"
          aria-hidden="true"
        >
          {edges.map((edge) => {
            const source = nodes.find((n) => n.node_id === edge.source_node_id);
            const target = nodes.find((n) => n.node_id === edge.target_node_id);
            if (!source || !target) return null;
            const from = centerOf(source);
            const to = centerOf(target);
            const midX = (from.x + to.x) / 2;
            return (
              <g key={edge.edge_id}>
                <path
                  d={`M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`}
                  fill="none"
                  stroke={edge.edge_kind === "error" ? "#e11d48" : "#64748b"}
                  strokeWidth={1.5}
                  strokeDasharray={edge.edge_kind === "error" ? "4 3" : undefined}
                />
                <text x={midX} y={(from.y + to.y) / 2} fontSize={9} fill="#475569">
                  {edge.condition ? "cond" : ""}
                </text>
              </g>
            );
          })}
        </svg>
        {nodes.map((node) => {
          const position = positionOf(node);
          const selected = node.node_id === selectedNodeId;
          const state =
            nodeStates?.[node.node_id] ??
            ({ status: "unexecuted", activationCount: 0, latestAttempt: 0 } as const);
          const style = RUN_STATUS_STYLE[state.status];
          const boxClass =
            readOnly && style.box ? style.box : nodeTypeClass(node.node_type);
          return (
            <div
              key={node.node_id}
              data-testid={`workflow-node-${node.node_id}`}
              data-selected={selected || undefined}
              data-status={readOnly ? state.status : undefined}
              data-activation-count={readOnly ? state.activationCount : undefined}
              role={readOnly ? "button" : undefined}
              tabIndex={readOnly ? 0 : undefined}
              className={`absolute rounded border-2 px-2 py-1 text-xs shadow-sm ${boxClass} ${
                draggable ? "cursor-grab" : "cursor-pointer"
              } ${selected ? "ring-2 ring-slate-800" : ""}`}
              style={{
                left: position.x,
                top: position.y,
                width: NODE_WIDTH,
                minHeight: NODE_HEIGHT,
                touchAction: "none",
              }}
              onPointerDown={draggable ? (event) => startDrag(event, node) : undefined}
              onClick={
                readOnly ? () => onSelectNode(node.node_id) : undefined
              }
              onKeyDown={
                readOnly
                  ? (event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelectNode(node.node_id);
                      }
                    }
                  : undefined
              }
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-semibold">{node.node_type}</span>
                <span className="flex shrink-0 items-center gap-1">
                  {scopeOf(node) && (
                    <span className="rounded bg-white px-1 text-[10px] text-slate-500">
                      loop内
                    </span>
                  )}
                  {state.activationCount > 1 && (
                    <span
                      data-testid={`workflow-node-count-${node.node_id}`}
                      className="rounded bg-white px-1 text-[10px] text-slate-600"
                    >
                      ×{state.activationCount}
                    </span>
                  )}
                  {readOnly && state.status !== "unexecuted" && (
                    <span
                      className={`rounded px-1 text-[10px] ${style.badge}`}
                    >
                      {RUN_GRAPH_STATUS_LABELS[state.status]}
                    </span>
                  )}
                </span>
              </div>
              <div className="truncate text-[11px] text-slate-700">
                {nodeDisplayName(node)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

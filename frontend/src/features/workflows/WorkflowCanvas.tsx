import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { WorkflowEdge, WorkflowNode } from "../../api/types";
import { scopeOf } from "./graphModel";

const NODE_WIDTH = 180;
const NODE_HEIGHT = 64;
const CANVAS_WIDTH = 960;
const CANVAS_HEIGHT = 560;

export interface WorkflowCanvasProps {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string | null) => void;
  onMoveNode: (nodeId: string, position: { x: number; y: number }) => void;
}

function positionOf(node: WorkflowNode): { x: number; y: number } {
  return node.ui_position ?? { x: 40, y: 40 };
}

function nodeTypeClass(nodeType: WorkflowNode["node_type"]): string {
  switch (nodeType) {
    case "capability":
      return "border-blue-400 bg-blue-50";
    case "agent":
      return "border-purple-400 bg-purple-50";
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
}: WorkflowCanvasProps) {
  const [drag, setDrag] = useState<{ nodeId: string; dx: number; dy: number } | null>(
    null,
  );
  const containerRef = useRef<HTMLDivElement>(null);

  const startDrag = (
    event: ReactPointerEvent<HTMLDivElement>,
    node: WorkflowNode,
  ) => {
    const position = positionOf(node);
    const rect = containerRef.current?.getBoundingClientRect();
    setDrag({
      nodeId: node.node_id,
      dx: event.clientX - (rect?.left ?? 0) - position.x,
      dy: event.clientY - (rect?.top ?? 0) - position.y,
    });
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
    onSelectNode(node.node_id);
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const x = Math.max(0, Math.min(CANVAS_WIDTH - NODE_WIDTH, event.clientX - rect.left - drag.dx));
    const y = Math.max(0, Math.min(CANVAS_HEIGHT - NODE_HEIGHT, event.clientY - rect.top - drag.dy));
    onMoveNode(drag.nodeId, { x, y });
  };

  const endDrag = () => setDrag(null);

  const centerOf = (node: WorkflowNode) => {
    const position = positionOf(node);
    return { x: position.x + NODE_WIDTH / 2, y: position.y + NODE_HEIGHT / 2 };
  };

  return (
    <div
      ref={containerRef}
      data-testid="workflow-canvas"
      className="relative overflow-auto rounded border border-slate-200 bg-slate-50"
      style={{ width: "100%", height: CANVAS_HEIGHT }}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
    >
      <div style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT, position: "relative" }}>
        <svg
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
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
          return (
            <div
              key={node.node_id}
              data-testid={`workflow-node-${node.node_id}`}
              data-selected={selected || undefined}
              className={`absolute cursor-grab rounded border-2 px-2 py-1 text-xs shadow-sm ${nodeTypeClass(
                node.node_type,
              )} ${selected ? "ring-2 ring-slate-800" : ""}`}
              style={{
                left: position.x,
                top: position.y,
                width: NODE_WIDTH,
                minHeight: NODE_HEIGHT,
                touchAction: "none",
              }}
              onPointerDown={(event) => startDrag(event, node)}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">{node.node_type}</span>
                {scopeOf(node) && (
                  <span className="rounded bg-white px-1 text-[10px] text-slate-500">
                    loop内
                  </span>
                )}
              </div>
              <div className="truncate text-[11px] text-slate-700">
                {String(
                  (node.config as Record<string, unknown>).capability_key ??
                    (node.config as Record<string, unknown>).agent_id ??
                    (node.config as Record<string, unknown>).outcome ??
                    node.label ??
                    node.node_id,
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

"""Copy a workflow graph with fresh node/edge ids.

Revision cloning, code-defined template instantiation, user-template
instantiation and definition-package import all need the same behaviour:
assign new ids to every node and edge, then rewrite every graph-local
reference (``$ref`` paths, loop ``entry_node_id``, ``parent_loop_node_id``
and edge conditions) so the copied graph stays internally consistent.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Optional

from obsidian_ai_hub.workflow.models import remap_node_references


def new_uuid() -> str:
    return str(uuid.uuid4())


def renumber_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    id_factory: Optional[Callable[[], str]] = None,
    default_positions: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return nodes/edges with fresh ids and rewritten graph-local references.

    ``id_factory`` defaults to UUID4. When ``default_positions`` is true, nodes
    without a ``ui_position`` get a simple grid position (used by the
    code-defined templates whose definitions carry no layout).
    """
    factory = id_factory or new_uuid
    id_map = {str(node["node_id"]): factory() for node in nodes}
    cloned_nodes: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        parent = node.get("parent_loop_node_id")
        config = remap_node_references(node.get("config") or {}, id_map)
        if isinstance(config, dict) and config.get("entry_node_id") in id_map:
            config["entry_node_id"] = id_map[config["entry_node_id"]]
        ui_position = node.get("ui_position")
        if ui_position is None and default_positions:
            ui_position = {
                "x": 40 + (index % 4) * 220,
                "y": 40 + (index // 4) * 120,
            }
        cloned_nodes.append(
            {
                "node_id": id_map[str(node["node_id"])],
                "node_type": node["node_type"],
                "label": node.get("label"),
                "config": config,
                "parent_loop_node_id": id_map.get(str(parent)) if parent else None,
                "ui_position": ui_position,
            }
        )
    cloned_edges = [
        {
            "edge_id": factory(),
            "source_node_id": id_map[str(edge["source_node_id"])],
            "target_node_id": id_map[str(edge["target_node_id"])],
            "edge_kind": edge.get("edge_kind") or "normal",
            "condition": remap_node_references(edge.get("condition"), id_map),
            "order_index": int(edge.get("order_index") or 0),
        }
        for edge in edges
    ]
    return cloned_nodes, cloned_edges

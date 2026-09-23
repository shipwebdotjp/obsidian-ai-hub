"""JSON/YAML workflow definition package v1.

The package is the portable representation of a workflow graph: format,
version, display name/description, ``inputs_schema`` and the Node/Edge graph.
It deliberately excludes Workflow / Revision / Template ids, status, Runs,
Events and Scheduler configuration. Node and Edge ids are graph-local and are
renumbered on import / instantiation.

Parsing is a trust boundary: it runs before any DB write and rejects malformed
or oversized packages with :class:`DefinitionPackageError` so callers can stop
without side effects.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from obsidian_ai_hub.workflow.models import (
    EDGE_KINDS,
    MAX_EDGES,
    MAX_NODES,
    NODE_TYPES,
)

PACKAGE_FORMAT = "obsidian-ai-hub.workflow-definition"
PACKAGE_VERSION = 1
MAX_PACKAGE_BYTES = 1_048_576
SUPPORTED_FORMATS = ("json", "yaml")

_TOP_KEYS = {
    "format",
    "version",
    "name",
    "description",
    "inputs_schema",
    "nodes",
    "edges",
}
_NODE_KEYS = {
    "node_id",
    "node_type",
    "label",
    "config",
    "parent_loop_node_id",
    "ui_position",
}
_EDGE_KEYS = {
    "edge_id",
    "source_node_id",
    "target_node_id",
    "edge_kind",
    "condition",
    "order_index",
}


class DefinitionPackageError(ValueError):
    """Raised when a definition package violates the v1 boundary contract."""


def _package_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": str(node["node_id"]),
        "node_type": node.get("node_type"),
        "label": node.get("label"),
        "config": node.get("config") or {},
        "parent_loop_node_id": node.get("parent_loop_node_id"),
        "ui_position": node.get("ui_position"),
    }


def _package_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": str(edge["edge_id"]),
        "source_node_id": str(edge["source_node_id"]),
        "target_node_id": str(edge["target_node_id"]),
        "edge_kind": edge.get("edge_kind") or "normal",
        "condition": edge.get("condition"),
        "order_index": int(edge.get("order_index") or 0),
    }


def build_package(
    name: str,
    description: str,
    inputs_schema: Any,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Project a stored graph into a v1 package (allowed keys only)."""
    return {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "name": name,
        "description": description or "",
        "inputs_schema": inputs_schema or {"type": "object"},
        "nodes": [_package_node(node) for node in nodes],
        "edges": [_package_edge(edge) for edge in edges],
    }


def serialize_package(package: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(package, ensure_ascii=False, indent=2)
    if fmt == "yaml":
        return yaml.safe_dump(
            package,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    raise DefinitionPackageError(f"未対応の形式です: {fmt}")


def _unknown_keys(data: dict[str, Any], allowed: set[str], path: str) -> list[str]:
    return [f"{path}: 未知のキー '{key}'" for key in data if key not in allowed]


def _validate_node(
    raw: Any, index: int, seen_node_ids: set[str]
) -> tuple[dict[str, Any], list[str]]:
    path = f"nodes[{index}]"
    errors: list[str] = []
    if not isinstance(raw, dict):
        return {}, [f"{path}: object が必要です"]
    errors.extend(_unknown_keys(raw, _NODE_KEYS, path))
    node_id = raw.get("node_id")
    if not isinstance(node_id, str) or not node_id.strip():
        errors.append(f"{path}.node_id: 空でない文字列が必要です")
    elif node_id in seen_node_ids:
        errors.append(f"{path}.node_id: '{node_id}' が重複しています")
    else:
        seen_node_ids.add(node_id)
    node_type = raw.get("node_type")
    if node_type not in NODE_TYPES:
        errors.append(f"{path}.node_type: {NODE_TYPES} のいずれかが必要です")
    config = raw.get("config", {})
    if not isinstance(config, dict):
        errors.append(f"{path}.config: object が必要です")
    parent = raw.get("parent_loop_node_id")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        errors.append(f"{path}.parent_loop_node_id: 文字列または null が必要です")
    position = raw.get("ui_position")
    if position is not None and not isinstance(position, dict):
        errors.append(f"{path}.ui_position: object または null が必要です")
    normalized = _package_node(raw) if not errors else {}
    return normalized, errors


def _validate_edge(
    raw: Any, index: int, node_ids: set[str], seen_edge_ids: set[str]
) -> tuple[dict[str, Any], list[str]]:
    path = f"edges[{index}]"
    errors: list[str] = []
    if not isinstance(raw, dict):
        return {}, [f"{path}: object が必要です"]
    errors.extend(_unknown_keys(raw, _EDGE_KEYS, path))
    edge_id = raw.get("edge_id")
    if not isinstance(edge_id, str) or not edge_id.strip():
        errors.append(f"{path}.edge_id: 空でない文字列が必要です")
    elif edge_id in seen_edge_ids:
        errors.append(f"{path}.edge_id: '{edge_id}' が重複しています")
    else:
        seen_edge_ids.add(edge_id)
    source = raw.get("source_node_id")
    target = raw.get("target_node_id")
    if not isinstance(source, str) or source not in node_ids:
        errors.append(f"{path}.source_node_id: Node '{source}' が存在しません")
    if not isinstance(target, str) or target not in node_ids:
        errors.append(f"{path}.target_node_id: Node '{target}' が存在しません")
    edge_kind = raw.get("edge_kind", "normal")
    if edge_kind not in EDGE_KINDS:
        errors.append(f"{path}.edge_kind: {EDGE_KINDS} のいずれかが必要です")
    order_index = raw.get("order_index", 0)
    if isinstance(order_index, bool) or not isinstance(order_index, int):
        errors.append(f"{path}.order_index: 整数が必要です")
    normalized = _package_edge(raw) if not errors else {}
    return normalized, errors


def validate_package(data: Any) -> dict[str, Any]:
    """Validate a decoded package object and return its normalized form."""
    if not isinstance(data, dict):
        raise DefinitionPackageError("package は object である必要があります")
    errors = _unknown_keys(data, _TOP_KEYS, "package")
    if data.get("format") != PACKAGE_FORMAT:
        errors.append(f"format: '{PACKAGE_FORMAT}' が必要です")
    if data.get("version") != PACKAGE_VERSION:
        errors.append(f"version: {PACKAGE_VERSION} が必要です")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name: 空でない文字列が必要です")
    description = data.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        errors.append("description: 文字列が必要です")
    inputs_schema = data.get("inputs_schema")
    if not isinstance(inputs_schema, dict):
        errors.append("inputs_schema: object が必要です")
    raw_nodes = data.get("nodes")
    raw_edges = data.get("edges")
    if not isinstance(raw_nodes, list):
        errors.append("nodes: 配列が必要です")
        raw_nodes = []
    if not isinstance(raw_edges, list):
        errors.append("edges: 配列が必要です")
        raw_edges = []
    if len(raw_nodes) > MAX_NODES:
        errors.append(f"nodes: 上限 {MAX_NODES} を超えています")
    if len(raw_edges) > MAX_EDGES:
        errors.append(f"edges: 上限 {MAX_EDGES} を超えています")

    seen_node_ids: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_nodes):
        node, node_errors = _validate_node(raw, index, seen_node_ids)
        errors.extend(node_errors)
        if not node_errors:
            nodes.append(node)

    node_ids = {str(node["node_id"]) for node in nodes}
    node_types = {str(node["node_id"]): node["node_type"] for node in nodes}
    for node in nodes:
        parent = node.get("parent_loop_node_id")
        if parent is not None and parent not in node_ids:
            errors.append(
                f"nodes: parent_loop_node_id '{parent}' が存在しません"
            )
        elif parent is not None and node_types.get(str(parent)) != "loop":
            errors.append(
                f"nodes: parent_loop_node_id '{parent}' は Loop Node ではありません"
            )
        if node.get("node_type") == "loop":
            entry = (node.get("config") or {}).get("entry_node_id")
            if entry is not None and (
                not isinstance(entry, str) or entry not in node_ids
            ):
                errors.append(
                    f"nodes: loop entry_node_id '{entry}' が存在しません"
                )

    seen_edge_ids: set[str] = set()
    edges: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_edges):
        edge, edge_errors = _validate_edge(raw, index, node_ids, seen_edge_ids)
        errors.extend(edge_errors)
        if not edge_errors:
            edges.append(edge)

    if errors:
        raise DefinitionPackageError("; ".join(errors))
    return {
        "format": PACKAGE_FORMAT,
        "version": PACKAGE_VERSION,
        "name": name.strip(),
        "description": description,
        "inputs_schema": inputs_schema,
        "nodes": nodes,
        "edges": edges,
    }


def parse_package(raw: bytes, fmt: str) -> dict[str, Any]:
    """Safely decode and validate a package body. Never writes to the DB."""
    if fmt not in SUPPORTED_FORMATS:
        raise DefinitionPackageError(f"未対応の形式です: {fmt}")
    if len(raw) > MAX_PACKAGE_BYTES:
        raise DefinitionPackageError(
            f"package のサイズが上限 {MAX_PACKAGE_BYTES} bytes を超えています"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DefinitionPackageError("package は UTF-8 である必要があります") from exc
    if fmt == "json":
        try:
            data = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise DefinitionPackageError(f"JSON の解析に失敗しました: {exc}") from exc
    else:
        try:
            data = yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError) as exc:
            raise DefinitionPackageError(f"YAML の解析に失敗しました: {exc}") from exc
    return validate_package(data)


def package_to_graph(
    package: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the raw (graph-local id) nodes and edges of a validated package."""
    return list(package["nodes"]), list(package["edges"])

"""Static validation for workflow revisions (graph + schemas + references).

Pure functions: callers supply the capability/agent existence checks so this
module stays testable without the database. ``docs/workflow/specification.md``
§6 is the contract.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Optional

from obsidian_ai_hub.workflow.models import (
    EDGE_KINDS,
    MAX_EDGES,
    MAX_ITERATIONS,
    MAX_NODES,
    NODE_TYPES,
    TERMINAL_OUTCOMES,
    TEXT_OUTPUT_KEY,
    iter_expressions,
    iter_invalid_reference_shapes,
    iter_piped_reference_entries,
    iter_references,
    reference_root,
    validate_condition,
    validate_expression,
    validate_pipe,
    validate_schema_subset,
)
from obsidian_ai_hub.workflow.llm_node import validate_llm_config
from obsidian_ai_hub.workflow.text_template import validate_template

CapabilityCheck = Callable[[str], bool]
AgentCheck = Callable[[str], bool]

_INDEX_SUFFIX_RE = re.compile(r"\[\d+\]$")


def _base_token(token: str) -> str:
    """Strip a trailing ``[N]`` index so ``items[0]`` maps to ``items``."""
    return _INDEX_SUFFIX_RE.sub("", token)


def _scope_of(node: dict[str, Any]) -> Optional[str]:
    parent = node.get("parent_loop_node_id")
    return str(parent) if parent else None


def _nodes_by_scope(nodes: list[dict[str, Any]]) -> dict[Optional[str], list[dict]]:
    scopes: dict[Optional[str], list[dict]] = defaultdict(list)
    for node in nodes:
        scopes[_scope_of(node)].append(node)
    return scopes


def _outgoing(edges: list[dict[str, Any]], scope_ids: set[str]) -> dict[str, list[dict]]:
    adjacency: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["source_node_id"] in scope_ids and edge["target_node_id"] in scope_ids:
            adjacency[edge["source_node_id"]].append(edge)
    for entries in adjacency.values():
        entries.sort(key=lambda e: int(e.get("order_index") or 0))
    return adjacency


def _detect_cycle(scope_ids: set[str], adjacency: dict[str, list[dict]]) -> bool:
    color: dict[str, int] = {}
    cycle = False

    def visit(node_id: str) -> None:
        nonlocal cycle
        color[node_id] = 1
        for edge in adjacency.get(node_id, []):
            target = edge["target_node_id"]
            if color.get(target) == 1:
                cycle = True
            elif color.get(target, 0) == 0:
                visit(target)
        color[node_id] = 2

    for node_id in scope_ids:
        if color.get(node_id, 0) == 0:
            visit(node_id)
    return cycle


def _reachable(adjacency: dict[str, list[dict]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for edge in adjacency.get(current, []):
            stack.append(edge["target_node_id"])
    return seen


def _incoming(edges: list[dict[str, Any]], scope_ids: set[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        if edge["source_node_id"] in scope_ids and edge["target_node_id"] in scope_ids:
            counts[edge["target_node_id"]] += 1
    return counts


def _reference_errors(
    ref: str,
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    path: str,
) -> list[str]:
    root = reference_root(ref)
    if root[:2] == ("run", "context"):
        if ref.split(".") == ["run", "context", "reference_time"]:
            return []
        return [f"reference_scope: {path}: 未対応の run.context 参照です: {ref}"]
    if root[:2] == ("run", "inputs"):
        properties = (inputs_schema or {}).get("properties")
        tokens = ref.split(".")
        field = _base_token(tokens[2]) if len(tokens) >= 3 else None
        if isinstance(properties, dict) and field is not None and field not in properties:
            return [f"reference_scope: {path}: run.inputs.{field} は inputs_schema にありません"]
        return []
    if root and root[0] == "nodes":
        tokens = ref.split(".")
        if len(tokens) < 3 or tokens[2] != "output":
            return [f"reference_scope: {path}: nodes 参照は nodes.<node_id>.output.* 形式が必要です"]
        if tokens[1] not in scope_ids:
            return [f"reference_scope: {path}: 参照先 Node '{tokens[1]}' は同一スコープにありません"]
        return []
    if root and root[0] == "loop":
        if root[:1] == ("loop",) and root[1:2] in (
            ("state",),
            ("input",),
            ("iteration",),
        ):
            if scope_id is None:
                return [f"reference_scope: {path}: loop.* 参照は Loop 子グラフ内でのみ使えます"]
            return []
        return [f"reference_scope: {path}: 未対応の loop 参照です"]
    return [f"reference_scope: {path}: 未対応の参照形式です: {ref}"]


def _condition_reference_errors(
    condition: Any,
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    path: str,
) -> list[str]:
    errors = validate_condition(condition, path=path)
    if errors or not isinstance(condition, dict):
        return errors
    return _reference_errors(
        str(condition["from_path"]),
        scope_id=scope_id,
        scope_ids=scope_ids,
        inputs_schema=inputs_schema,
        path=f"{path}.from_path",
    )


_PIPE_FIRST_OP_INPUT_TYPES: dict[str, frozenset[str]] = {
    "upper": frozenset({"string"}),
    "lower": frozenset({"string"}),
    "truncate": frozenset({"string"}),
    "replace": frozenset({"string"}),
    "slice": frozenset({"string", "array"}),
    "join": frozenset({"array"}),
    "pluck": frozenset({"array"}),
    "filter": frozenset({"array"}),
    "sort": frozenset({"array"}),
    "unique": frozenset({"array"}),
}


def _pipe_input_type_errors(
    ref: str,
    pipe: list[Any],
    *,
    resolver: Callable[[str], Optional[tuple[Optional[str], Optional[str]]]],
    path: str,
) -> list[str]:
    """Best-effort schema check: declared ref type vs the first op's input.

    Only the referenced value's declared type is known statically; later ops
    and opaque Capability outputs stay runtime-checked.
    """
    if not pipe or not isinstance(pipe[0], dict):
        return []
    op = pipe[0].get("op")
    expected = _PIPE_FIRST_OP_INPUT_TYPES.get(str(op))
    if expected is None:
        return []
    declared = resolver(ref)
    if declared is None:
        return []
    declared_type = declared[0]
    if declared_type is None or declared_type in expected:
        return []
    return [
        f"pipe_type: {path}: 演算子 '{op}' は {sorted(expected)} を要求しますが、"
        f"参照先の型は '{declared_type}' です"
    ]


def _value_reference_errors(
    value: Any,
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    path: str,
    nodes: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    errors: list[str] = []
    for ref in iter_references(value):
        errors.extend(
            _reference_errors(
                ref,
                scope_id=scope_id,
                scope_ids=scope_ids,
                inputs_schema=inputs_schema,
                path=path,
            )
        )
    resolver = (
        _anchor_type_resolver(nodes, inputs_schema, scope_id)
        if nodes is not None
        else None
    )
    for ref, pipe in iter_piped_reference_entries(value):
        errors.extend(validate_pipe(pipe, path=f"{path}.pipe"))
        if resolver is not None:
            errors.extend(
                _pipe_input_type_errors(
                    ref, pipe, resolver=resolver, path=f"{path}.pipe"
                )
            )
    for _ in iter_invalid_reference_shapes(value):
        errors.append(
            f"reference_shape: {path}: $ref / $expr の形式が不正です"
        )
    return errors


def _schema_field_type(
    schema: Any, tokens: list[str]
) -> Optional[tuple[Optional[str], Optional[str]]]:
    """Return ``(type, format)`` for a schema path, or None when unknown."""
    current = schema
    for token in tokens:
        if not isinstance(current, dict):
            return None
        if current.get("type") == "array":
            current = current.get("items")
            if not isinstance(current, dict):
                return None
        base = _base_token(str(token))
        props = current.get("properties")
        if not isinstance(props, dict) or base not in props:
            return None
        current = props[base]
        if _INDEX_SUFFIX_RE.search(str(token)):
            if not isinstance(current, dict) or current.get("type") != "array":
                return None
            current = current.get("items")
    if not isinstance(current, dict):
        return None
    return current.get("type"), current.get("format")


def _anchor_type_resolver(
    nodes: list[dict[str, Any]],
    inputs_schema: Optional[dict[str, Any]],
    scope_id: Optional[str],
) -> Callable[[str], Optional[tuple[Optional[str], Optional[str]]]]:
    """Best-effort declared-type lookup for a date-expression anchor ref.

    Returns ``None`` for positions whose type the backend cannot see (opaque
    Capability outputs); those are checked at execution time instead.
    """
    by_id = {str(n.get("node_id")): n for n in nodes}
    loop = by_id.get(scope_id) if scope_id else None
    loop_config = (loop or {}).get("config")
    loop_state = (
        loop_config.get("state_schema") if isinstance(loop_config, dict) else None
    )

    def resolve(ref: str) -> Optional[tuple[Optional[str], Optional[str]]]:
        segments = ref.split(".")
        if segments == ["run", "context", "reference_time"]:
            return ("string", "date-time")
        if segments[:2] == ["run", "inputs"]:
            return _schema_field_type(inputs_schema, segments[2:])
        if segments[:2] == ["loop", "state"]:
            return _schema_field_type(loop_state, segments[2:])
        if segments[:1] == ["nodes"] and len(segments) >= 3:
            node = by_id.get(segments[1])
            if node is None:
                return None
            tail = segments[3:]
            node_type = node.get("node_type")
            config = node.get("config")
            if not isinstance(config, dict):
                return None
            if node_type == "agent":
                return _schema_field_type(config.get("output_schema"), tail)
            if node_type == "llm":
                return _schema_field_type(config.get("output_schema"), tail)
            if node_type == "loop":
                if tail[:1] == ["final_state"]:
                    return _schema_field_type(config.get("state_schema"), tail[1:])
                return None
            if node_type == "loop_result":
                parent = by_id.get(str(node.get("parent_loop_node_id")))
                parent_config = (parent or {}).get("config")
                state_schema = (
                    parent_config.get("state_schema")
                    if isinstance(parent_config, dict)
                    else None
                )
                return _schema_field_type(state_schema, tail)
            if node_type == "text_template":
                if tail == [TEXT_OUTPUT_KEY]:
                    return ("string", None)
                return None
            return None
        return None

    return resolve


def _value_expression_errors(
    value: Any,
    *,
    nodes: list[dict[str, Any]],
    inputs_schema: Optional[dict[str, Any]],
    scope_id: Optional[str],
    path: str,
) -> list[str]:
    errors: list[str] = []
    resolver = _anchor_type_resolver(nodes, inputs_schema, scope_id)
    for expr in iter_expressions(value):
        errors.extend(
            validate_expression(
                {"$expr": expr}, path=path, anchor_type_resolver=resolver
            )
        )
    return errors


def validate_graph(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    inputs_schema: Optional[dict[str, Any]] = None,
    capability_enabled: Optional[CapabilityCheck] = None,
    agent_exists: Optional[AgentCheck] = None,
) -> list[str]:
    """Return a list of static validation errors for a revision graph."""
    errors: list[str] = []
    if len(nodes) > MAX_NODES:
        errors.append(f"Node 数が上限 {MAX_NODES} を超えています")
    if len(edges) > MAX_EDGES:
        errors.append(f"Edge 数が上限 {MAX_EDGES} を超えています")

    node_ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("node_id") or "")
        if not node_id:
            errors.append("node_id が空の Node があります")
            continue
        if node_id in node_ids:
            errors.append(f"node_id '{node_id}' が重複しています")
        node_ids.add(node_id)
        by_id[node_id] = node

    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("edge_id") or "")
        if edge_id in edge_ids:
            errors.append(f"edge_id '{edge_id}' が重複しています")
        edge_ids.add(edge_id)
        if edge.get("edge_kind", "normal") not in EDGE_KINDS:
            errors.append(f"edge '{edge_id}': edge_kind が不正です")
        if edge["source_node_id"] not in by_id or edge["target_node_id"] not in by_id:
            errors.append(
                f"edge '{edge_id}': source/target Node が存在しません"
            )
            continue
        source = by_id[edge["source_node_id"]]
        target = by_id[edge["target_node_id"]]
        if _scope_of(source) != _scope_of(target):
            errors.append(
                f"edge '{edge_id}': 異なるスコープ間の Edge は作れません"
            )
        if source.get("node_type") == "terminal":
            errors.append(f"edge '{edge_id}': terminal Node に outgoing Edge があります")

    scopes = _nodes_by_scope(nodes)
    for scope_id, scope_nodes in scopes.items():
        scope_ids = {str(n["node_id"]) for n in scope_nodes}
        adjacency = _outgoing(edges, scope_ids)
        if _detect_cycle(scope_ids, adjacency):
            label = "トップレベル" if scope_id is None else f"loop '{scope_id}'"
            errors.append(f"cycle: {label}グラフに循環 Edge があります")

    for node in nodes:
        node_id = str(node["node_id"])
        node_type = node.get("node_type")
        config = node.get("config") or {}
        if not isinstance(config, dict):
            errors.append(f"Node '{node_id}': config は object が必要です")
            continue
        scope_id = _scope_of(node)
        scope_ids = {
            str(n["node_id"]) for n in scopes.get(scope_id, [])
        }
        if node_type not in NODE_TYPES:
            errors.append(f"Node '{node_id}': node_type '{node_type}' は不正です")
            continue
        if node_type == "terminal":
            if config.get("outcome") not in TERMINAL_OUTCOMES:
                errors.append(
                    f"Node '{node_id}': terminal.outcome が不正です"
                )
        elif node_type == "capability":
            errors.extend(
                _validate_capability_node(
                    node_id,
                    config,
                    scope_id=scope_id,
                    scope_ids=scope_ids,
                    inputs_schema=inputs_schema,
                    nodes=nodes,
                    capability_enabled=capability_enabled,
                )
            )
        elif node_type == "agent":
            errors.extend(
                _validate_agent_node(
                    node_id,
                    config,
                    scope_id=scope_id,
                    scope_ids=scope_ids,
                    inputs_schema=inputs_schema,
                    nodes=nodes,
                    agent_exists=agent_exists,
                )
            )
        elif node_type == "llm":
            errors.extend(
                _validate_llm_node(
                    node_id,
                    config,
                    scope_id=scope_id,
                    scope_ids=scope_ids,
                    inputs_schema=inputs_schema,
                    nodes=nodes,
                )
            )
        elif node_type == "loop":
            if scope_id is not None:
                errors.append(f"loop_nested: Node '{node_id}': Loop Node のネストは未対応です")
            errors.extend(
                _validate_loop_node(
                    node_id,
                    config,
                    nodes=nodes,
                    edges=edges,
                    inputs_schema=inputs_schema,
                )
            )
        elif node_type == "loop_result":
            if scope_id is None:
                errors.append(
                    f"loop_scope: Node '{node_id}': loop_result は Loop 子グラフ内でのみ使えます"
                )
            output_mapping = config.get("output_mapping")
            if not isinstance(output_mapping, dict):
                errors.append(
                    f"Node '{node_id}': loop_result.output_mapping は object が必要です"
                )
            else:
                errors.extend(
                    _value_reference_errors(
                        output_mapping,
                        scope_id=scope_id,
                        scope_ids=scope_ids,
                        inputs_schema=inputs_schema,
                        nodes=nodes,
                        path=f"Node '{node_id}'.output_mapping",
                    )
                )
        elif node_type == "text_template":
            errors.extend(
                _validate_text_template_node(
                    node_id,
                    config,
                    scope_id=scope_id,
                    scope_ids=scope_ids,
                    inputs_schema=inputs_schema,
                    nodes=nodes,
                )
            )

        expression_key = {
            "capability": "inputs",
            "agent": "inputs",
            "llm": "inputs",
            "loop": "input_mapping",
            "loop_result": "output_mapping",
            "text_template": "inputs",
        }.get(str(node_type))
        if expression_key is not None:
            errors.extend(
                _value_expression_errors(
                    config.get(expression_key),
                    nodes=nodes,
                    inputs_schema=inputs_schema,
                    scope_id=scope_id,
                    path=f"Node '{node_id}'.{expression_key}",
                )
            )

    for edge in edges:
        if edge["source_node_id"] not in by_id:
            continue
        source = by_id[edge["source_node_id"]]
        scope_id = _scope_of(source)
        scope_ids = {str(n["node_id"]) for n in scopes.get(scope_id, [])}
        if edge.get("condition") is not None:
            errors.extend(
                _condition_reference_errors(
                    edge["condition"],
                    scope_id=scope_id,
                    scope_ids=scope_ids,
                    inputs_schema=inputs_schema,
                    path=f"edge '{edge['edge_id']}'.condition",
                )
            )

    errors.extend(
        _validate_scope_connectivity(scopes, edges)
    )
    return errors


def _validate_capability_node(
    node_id: str,
    config: dict[str, Any],
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    nodes: Optional[list[dict[str, Any]]] = None,
    capability_enabled: Optional[CapabilityCheck],
) -> list[str]:
    errors: list[str] = []
    key = config.get("capability_key")
    if not isinstance(key, str) or not key.strip():
        errors.append(f"Node '{node_id}': capability_key が必要です")
    elif capability_enabled is not None and not capability_enabled(key):
        errors.append(f"Node '{node_id}': Capability '{key}' は無効です")
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(f"Node '{node_id}': inputs は object が必要です")
        return errors
    errors.extend(
        _value_reference_errors(
            inputs,
            scope_id=scope_id,
            scope_ids=scope_ids,
            inputs_schema=inputs_schema,
            nodes=nodes,
            path=f"Node '{node_id}'.inputs",
        )
    )
    if isinstance(key, str) and key.strip():
        from obsidian_ai_hub.tasks.capability_schemas import (
            capability_has_target,
            validate_capability_target,
        )

        if capability_has_target(key):
            target = config.get("target")
            if not isinstance(target, dict) or not target:
                errors.append(f"Node '{node_id}': target が必要です")
            else:
                try:
                    validate_capability_target(key, target)
                except ValueError as exc:
                    errors.append(f"Node '{node_id}': target が不正です: {exc}")
    retry = config.get("retry")
    if retry is not None:
        attempts = retry.get("max_attempts") if isinstance(retry, dict) else None
        if attempts is not None and (
            isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0
        ):
            errors.append(f"Node '{node_id}': retry.max_attempts は非負整数が必要です")
    strict = config.get("fail_on_output_mismatch")
    if strict is not None and not isinstance(strict, bool):
        errors.append(
            f"Node '{node_id}': fail_on_output_mismatch は boolean が必要です"
        )
    return errors


def _validate_agent_node(
    node_id: str,
    config: dict[str, Any],
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    nodes: Optional[list[dict[str, Any]]] = None,
    agent_exists: Optional[AgentCheck],
) -> list[str]:
    errors: list[str] = []
    agent_id = config.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        errors.append(f"Node '{node_id}': agent_id が必要です")
    elif agent_exists is not None and not agent_exists(agent_id):
        errors.append(f"Node '{node_id}': Agent '{agent_id}' が存在しません")
    output_schema = config.get("output_schema")
    if output_schema is None:
        errors.append(f"Node '{node_id}': output_schema が必要です")
    else:
        errors.extend(
            validate_schema_subset(
                output_schema, path=f"Node '{node_id}'.output_schema"
            )
        )
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(f"Node '{node_id}': inputs は object が必要です")
        return errors
    errors.extend(
        _value_reference_errors(
            inputs,
            scope_id=scope_id,
            scope_ids=scope_ids,
            inputs_schema=inputs_schema,
            nodes=nodes,
            path=f"Node '{node_id}'.inputs",
        )
    )
    return errors


def _validate_llm_node(
    node_id: str,
    config: dict[str, Any],
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    nodes: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_llm_config(config, path=f"Node '{node_id}'"))
    output_schema = config.get("output_schema")
    if output_schema is None:
        errors.append(f"Node '{node_id}': output_schema が必要です")
    else:
        errors.extend(
            validate_schema_subset(
                output_schema, path=f"Node '{node_id}'.output_schema"
            )
        )
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(f"Node '{node_id}': inputs は object が必要です")
        return errors
    errors.extend(
        _value_reference_errors(
            inputs,
            scope_id=scope_id,
            scope_ids=scope_ids,
            inputs_schema=inputs_schema,
            nodes=nodes,
            path=f"Node '{node_id}'.inputs",
        )
    )
    return errors


def _validate_text_template_node(
    node_id: str,
    config: dict[str, Any],
    *,
    scope_id: Optional[str],
    scope_ids: set[str],
    inputs_schema: Optional[dict[str, Any]],
    nodes: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    errors: list[str] = []
    inputs = config.get("inputs", {})
    if not isinstance(inputs, dict):
        errors.append(f"Node '{node_id}': inputs は object が必要です")
        return errors
    errors.extend(
        _value_reference_errors(
            inputs,
            scope_id=scope_id,
            scope_ids=scope_ids,
            inputs_schema=inputs_schema,
            nodes=nodes,
            path=f"Node '{node_id}'.inputs",
        )
    )
    errors.extend(
        validate_template(
            config.get("template"),
            allowed_variables=inputs.keys(),
            path=f"Node '{node_id}'.template",
        )
    )
    return errors


def _validate_loop_node(
    node_id: str,
    config: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    inputs_schema: Optional[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    state_schema = config.get("state_schema")
    if state_schema is None:
        errors.append(f"Node '{node_id}': state_schema が必要です")
    else:
        errors.extend(
            validate_schema_subset(state_schema, path=f"Node '{node_id}'.state_schema")
        )
    input_mapping = config.get("input_mapping")
    if not isinstance(input_mapping, dict):
        errors.append(f"Node '{node_id}': input_mapping は object が必要です")
    else:
        errors.extend(
            _value_reference_errors(
                input_mapping,
                scope_id=None,
                scope_ids={str(n["node_id"]) for n in nodes if not n.get("parent_loop_node_id")},
                inputs_schema=inputs_schema,
                nodes=nodes,
                path=f"Node '{node_id}'.input_mapping",
            )
        )
    errors.extend(
        _condition_reference_errors(
            config.get("continuation_condition"),
            scope_id=node_id,
            scope_ids={str(n["node_id"]) for n in nodes if n.get("parent_loop_node_id") == node_id},
            inputs_schema=inputs_schema,
            path=f"Node '{node_id}'.continuation_condition",
        )
    )
    max_iterations = config.get("max_iterations")
    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or max_iterations < 1
        or max_iterations > MAX_ITERATIONS
    ):
        errors.append(
            f"Node '{node_id}': max_iterations は 1..{MAX_ITERATIONS} が必要です"
        )

    child_nodes = [n for n in nodes if n.get("parent_loop_node_id") == node_id]
    child_ids = {str(n["node_id"]) for n in child_nodes}
    entry_node_id = config.get("entry_node_id")
    if not isinstance(entry_node_id, str) or entry_node_id not in child_ids:
        errors.append(
            f"Node '{node_id}': entry_node_id は子グラフの Node を指す必要があります"
        )
    loop_results = [n for n in child_nodes if n.get("node_type") == "loop_result"]
    if len(loop_results) != 1:
        errors.append(
            f"loop_result_count: Node '{node_id}': 子グラフには loop_result がちょうど 1 つ必要です"
        )
    if any(n.get("node_type") == "loop" for n in child_nodes):
        errors.append(f"loop_nested: Node '{node_id}': 子グラフ内の Loop ネストは未対応です")
    if isinstance(entry_node_id, str) and loop_results:
        child_edges = [
            e
            for e in edges
            if e["source_node_id"] in child_ids and e["target_node_id"] in child_ids
        ]
        adjacency = _outgoing(child_edges, child_ids)
        reachable = _reachable(adjacency, entry_node_id)
        if reachable != child_ids:
            missing = sorted(child_ids - reachable)
            errors.append(
                f"Node '{node_id}': entry から到達できない子 Node があります: {missing}"
            )
        result_id = str(loop_results[0]["node_id"])
        reverse = _outgoing(
            [
                {
                    "source_node_id": e["target_node_id"],
                    "target_node_id": e["source_node_id"],
                    "order_index": 0,
                }
                for e in child_edges
            ],
            child_ids,
        )
        can_reach_result = _reachable(reverse, result_id)
        orphan = sorted(
            cid for cid in child_ids if cid != result_id and cid not in can_reach_result
        )
        if orphan:
            errors.append(
                f"Node '{node_id}': loop_result に到達できない子 Node があります: {orphan}"
            )
    return errors


def collect_graph_warnings(
    *,
    nodes: list[dict[str, Any]],
    read_only: Optional[Callable[[str], bool]] = None,
) -> list[str]:
    """Return non-blocking warnings for a revision graph.

    Currently flags capability Nodes whose capability can write or perform an
    external operation, so a mostly read-only workflow does not silently gain
    write authority. Warnings never block save or publish.
    """
    if read_only is None:
        return []
    warnings: list[str] = []
    for node in nodes or []:
        if node.get("node_type") != "capability":
            continue
        config = node.get("config") or {}
        if not isinstance(config, dict):
            continue
        key = str(config.get("capability_key") or "")
        if not key:
            continue
        if not read_only(key):
            warnings.append(
                f"Node '{node.get('node_id')}': Capability '{key}' は書込・外部操作を含みます"
            )
        strict = config.get("fail_on_output_mismatch") is True
        retry = config.get("retry")
        attempts = retry.get("max_attempts") if isinstance(retry, dict) else None
        if (
            strict
            and isinstance(attempts, int)
            and not isinstance(attempts, bool)
            and attempts > 0
        ):
            warnings.append(
                f"Node '{node.get('node_id')}': strict 出力と retry の併用は、"
                "契約違反時に副作用が再実行されうるため非推奨です"
            )
    return warnings


def _validate_scope_connectivity(
    scopes: dict[Optional[str], list[dict[str, Any]]],
    edges: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    for scope_id, scope_nodes in scopes.items():
        if scope_id is not None:
            # Loop child connectivity is handled by _validate_loop_node.
            continue
        scope_ids = {str(n["node_id"]) for n in scope_nodes}
        incoming = _incoming(edges, scope_ids)
        entries = [
            nid for nid in scope_ids if incoming.get(nid, 0) == 0
        ]
        if len(entries) != 1:
            errors.append(
                "entry_count: トップレベルグラフには incoming Edge のない entry Node が"
                f"ちょうど 1 つ必要です（現在 {len(entries)} 個）"
            )
            continue
        adjacency = _outgoing(edges, scope_ids)
        reachable = _reachable(adjacency, entries[0])
        missing = sorted(scope_ids - reachable)
        if missing:
            errors.append(f"entry から到達できない Node があります: {missing}")
    return errors

"""Workflow graph primitives: statuses, JSON Schema subset, typed references.

This module is pure (no DB, no adapters) so the store, validation, engine and
tests all share one definition of statuses, condition operators and reference
grammar. See ``docs/workflow/specification.md`` for the contract.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

NODE_TYPES: tuple[str, ...] = (
    "capability",
    "agent",
    "loop",
    "terminal",
    "loop_result",
)
TERMINAL_OUTCOMES: tuple[str, ...] = ("success", "failure")
EDGE_KINDS: tuple[str, ...] = ("normal", "error")
CONDITION_OPERATORS: tuple[str, ...] = ("equals", "exists", "in")

RUN_STATUSES: tuple[str, ...] = (
    "queued",
    "waiting_approval",
    "running",
    "waiting_hitl",
    "waiting_attention",
    "cancelling",
    "interrupted",
    "completed",
    "incomplete",
    "failed",
    "cancelled",
)
RUN_TERMINAL_STATUSES = frozenset(
    {"completed", "incomplete", "failed", "cancelled"}
)
RUN_WAITING_STATUSES = frozenset(
    {"waiting_approval", "waiting_hitl", "waiting_attention"}
)
RUN_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"waiting_approval", "running", "cancelled", "failed"}),
    "waiting_approval": frozenset({"queued", "running", "cancelled"}),
    "running": frozenset(
        {
            "completed",
            "incomplete",
            "failed",
            "cancelling",
            "interrupted",
            "waiting_hitl",
            "waiting_attention",
        }
    ),
    "waiting_hitl": frozenset({"queued", "cancelled"}),
    "waiting_attention": frozenset(
        {"queued", "failed", "interrupted", "cancelled"}
    ),
    "cancelling": frozenset({"cancelled", "failed", "interrupted"}),
    "interrupted": frozenset({"queued", "cancelled"}),
}

NODE_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "waiting_hitl",
    "succeeded",
    "skipped",
    "failed",
    "needs_attention",
    "cancelled",
)
NODE_TERMINAL_STATUSES = frozenset(
    {"succeeded", "skipped", "failed", "cancelled"}
)

MAX_NODES = 30
MAX_ITERATIONS = 50
MAX_SCHEMA_DEPTH = 8

REF_KEY = "$ref"

_SUPPORTED_SCHEMA_KEYS = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "additionalProperties",
    "description",
    "title",
    "default",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
}
_UNSUPPORTED_SCHEMA_KEYS = {
    "$ref",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "const",
    "patternProperties",
    "additionalItems",
    "dependencies",
    "definitions",
    "$defs",
    "if",
    "then",
    "else",
    "propertyNames",
}
_SUBSET_TYPES = {"object", "array", "string", "integer", "number", "boolean"}


def validate_schema_subset(
    schema: Any, *, path: str = "schema", depth: int = 0
) -> list[str]:
    """Validate that ``schema`` stays inside the v1 JSON Schema subset.

    Returns a list of human-readable errors (empty means valid). The subset is
    intentionally small: object/properties/required, arrays, primitives, enum
    and additionalProperties. ``$ref``/``oneOf``/recursion are rejected.
    """
    errors: list[str] = []
    if depth > MAX_SCHEMA_DEPTH:
        return [f"{path}: schema のネストが深すぎます"]
    if not isinstance(schema, dict):
        return [f"{path}: schema は object である必要があります"]
    for key in schema:
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            errors.append(f"{path}: '{key}' は v1 では未対応です")
        elif key not in _SUPPORTED_SCHEMA_KEYS:
            errors.append(f"{path}: 未知の schema キー '{key}'")
    stype = schema.get("type")
    if stype is not None and stype not in _SUBSET_TYPES:
        errors.append(f"{path}: type '{stype}' は v1 では未対応です")
    if stype is None and "enum" not in schema:
        errors.append(f"{path}: type または enum が必要です")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or not enum:
            errors.append(f"{path}.enum: 空でない配列が必要です")
    if stype == "object":
        props = schema.get("properties")
        if props is not None and not isinstance(props, dict):
            errors.append(f"{path}.properties: object が必要です")
            props = None
        if isinstance(props, dict):
            for name, sub in props.items():
                errors.extend(
                    validate_schema_subset(
                        sub, path=f"{path}.properties.{name}", depth=depth + 1
                    )
                )
        required = schema.get("required")
        if required is not None and (
            not isinstance(required, list)
            or any(not isinstance(r, str) for r in required)
        ):
            errors.append(f"{path}.required: 文字列の配列が必要です")
        elif isinstance(required, list) and isinstance(props, dict):
            for name in required:
                if name not in props:
                    errors.append(f"{path}.required: 未定義のプロパティ '{name}'")
        additional = schema.get("additionalProperties")
        if additional is not None and not isinstance(additional, bool):
            errors.append(f"{path}.additionalProperties: boolean のみ対応です")
    elif stype == "array":
        if "items" not in schema:
            errors.append(f"{path}: array には items が必要です")
        else:
            errors.extend(
                validate_schema_subset(
                    schema["items"], path=f"{path}.items", depth=depth + 1
                )
            )
    return errors


def validate_value_against_schema(
    value: Any, schema: Any, *, path: str = "value"
) -> list[str]:
    """Validate ``value`` against the v1 schema subset; returns error strings."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    if "enum" in schema:
        enum = schema["enum"]
        if isinstance(enum, list) and value not in enum:
            errors.append(f"{path}: {value!r} は enum に含まれません")
        return errors
    stype = schema.get("type")
    if stype == "object":
        if not isinstance(value, dict):
            return [f"{path}: object が必要です"]
        props = schema.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{path}: 必須プロパティ '{name}' がありません")
        if schema.get("additionalProperties") is False:
            for name in value:
                if name not in props:
                    errors.append(f"{path}: 未知のプロパティ '{name}'")
        for name, sub in props.items():
            if name in value:
                errors.extend(
                    validate_value_against_schema(
                        value[name], sub, path=f"{path}.{name}"
                    )
                )
    elif stype == "array":
        if not isinstance(value, list):
            return [f"{path}: array が必要です"]
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_value_against_schema(
                        item, items, path=f"{path}[{index}]"
                    )
                )
    elif stype == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: string が必要です")
    elif stype == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"{path}: integer が必要です")
    elif stype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: number が必要です")
    elif stype == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: boolean が必要です")
    return errors


def is_reference(value: Any) -> bool:
    """True when ``value`` is exactly ``{"$ref": "<path>"}``."""
    return (
        isinstance(value, dict)
        and set(value.keys()) == {REF_KEY}
        and isinstance(value.get(REF_KEY), str)
        and bool(value[REF_KEY].strip())
    )


def iter_references(value: Any) -> Iterable[str]:
    """Yield every ``$ref`` string contained in a nested config value."""
    if is_reference(value):
        yield value[REF_KEY]
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_references(child)


_NODE_REF_RE = re.compile(r"^nodes\.([^.]+)(\..*)?$")


def remap_node_references(value: Any, id_map: dict[str, str]) -> Any:
    """Return ``value`` with ``nodes.<id>`` references rewritten via ``id_map``.

    Used when copying a graph into a new revision (fresh node ids) so typed
    references keep pointing at the copied nodes.
    """
    if isinstance(value, str):
        match = _NODE_REF_RE.match(value)
        if match and match.group(1) in id_map:
            return f"nodes.{id_map[match.group(1)]}{match.group(2) or ''}"
        return value
    if isinstance(value, dict):
        return {
            key: remap_node_references(child, id_map)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [remap_node_references(child, id_map) for child in value]
    return value


_SEGMENT_RE = re.compile(r"^([^\[\]]+)((?:\[\d+\])*)$")
_INDEX_RE = re.compile(r"\[(\d+)\]")


def _path_segments(path: str) -> list[Any]:
    tokens: list[Any] = []
    for raw in path.split("."):
        if not raw:
            continue
        match = _SEGMENT_RE.match(raw)
        base = raw
        if match:
            base = match.group(1)
            tokens.append(base)
            tokens.extend(int(i) for i in _INDEX_RE.findall(match.group(2)))
        else:
            tokens.append(base)
    return tokens


def reference_root(ref: str) -> tuple[str, ...]:
    """Return the leading tokens that identify a reference's namespace."""
    return tuple(str(seg) for seg in _path_segments(ref)[:2])


def _walk(root: Any, tokens: list[Any], ref: str) -> Any:
    current = root
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                raise KeyError(f"参照 '{ref}' の index [{token}] が解決できません")
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                raise KeyError(f"参照 '{ref}' の '{token}' が解決できません")
            current = current[token]
    return current


def resolve_reference(
    ref: str,
    *,
    run_inputs: dict[str, Any],
    node_outputs: dict[str, Any],
    loop_state: Optional[dict[str, Any]] = None,
    loop_input: Optional[dict[str, Any]] = None,
    loop_iteration: Optional[int] = None,
) -> Any:
    """Resolve a typed reference to its current value.

    Raises ``KeyError`` when a path component is missing so the caller can
    fail the node before any external side effect.
    """
    segments = _path_segments(ref)
    if not segments:
        raise KeyError("空の参照は解決できません")
    head = segments[0]
    if head == "run" and len(segments) >= 3 and segments[1] == "inputs":
        return _walk(run_inputs, segments[2:], ref)
    if head == "nodes" and len(segments) >= 3 and segments[2] == "output":
        node_id = str(segments[1])
        if node_id not in node_outputs:
            raise KeyError(f"参照 '{ref}' の Node '{node_id}' は未実行です")
        return _walk(node_outputs[node_id], segments[3:], ref)
    if head == "loop":
        if segments[1:2] == ["iteration"]:
            if loop_iteration is None:
                raise KeyError(f"参照 '{ref}' は Loop 外では解決できません")
            return loop_iteration
        if segments[1:2] == ["state"]:
            if loop_state is None:
                raise KeyError(f"参照 '{ref}' は Loop 外では解決できません")
            return _walk(loop_state, segments[2:], ref)
        if segments[1:2] == ["input"]:
            if loop_input is None:
                raise KeyError(f"参照 '{ref}' は Loop 外では解決できません")
            return _walk(loop_input, segments[2:], ref)
    raise KeyError(f"未対応の参照形式です: {ref}")


def resolve_value(
    value: Any,
    *,
    run_inputs: dict[str, Any],
    node_outputs: dict[str, Any],
    loop_state: Optional[dict[str, Any]] = None,
    loop_input: Optional[dict[str, Any]] = None,
    loop_iteration: Optional[int] = None,
) -> Any:
    """Resolve references recursively; literals pass through unchanged."""
    if is_reference(value):
        return resolve_reference(
            value[REF_KEY],
            run_inputs=run_inputs,
            node_outputs=node_outputs,
            loop_state=loop_state,
            loop_input=loop_input,
            loop_iteration=loop_iteration,
        )
    if isinstance(value, dict):
        return {
            key: resolve_value(
                child,
                run_inputs=run_inputs,
                node_outputs=node_outputs,
                loop_state=loop_state,
                loop_input=loop_input,
                loop_iteration=loop_iteration,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_value(
                child,
                run_inputs=run_inputs,
                node_outputs=node_outputs,
                loop_state=loop_state,
                loop_input=loop_input,
                loop_iteration=loop_iteration,
            )
            for child in value
        ]
    return value


def validate_condition(condition: Any, *, path: str = "condition") -> list[str]:
    """Validate an edge/loop predicate object."""
    if not isinstance(condition, dict):
        return [f"{path}: object が必要です"]
    errors: list[str] = []
    from_path = condition.get("from_path")
    if not isinstance(from_path, str) or not from_path.strip():
        errors.append(f"{path}.from_path: 空でない文字列が必要です")
    operator = condition.get("operator")
    if operator not in CONDITION_OPERATORS:
        errors.append(f"{path}.operator: {CONDITION_OPERATORS} のいずれかが必要です")
    if operator in ("equals", "in") and "value" not in condition:
        errors.append(f"{path}.value: operator '{operator}' には value が必要です")
    if operator == "in" and "value" in condition and not isinstance(
        condition["value"], list
    ):
        errors.append(f"{path}.value: operator 'in' の value は配列が必要です")
    return errors


def evaluate_condition(condition: dict[str, Any], resolver: Any) -> bool:
    """Evaluate a predicate; ``resolver(from_path)`` returns the compared value."""
    value = resolver(str(condition["from_path"]))
    operator = condition.get("operator")
    if operator == "exists":
        return value is not None
    if operator == "equals":
        return value == condition.get("value")
    if operator == "in":
        container = condition.get("value")
        return isinstance(container, list) and value in container
    raise ValueError(f"Unknown condition operator: {operator!r}")

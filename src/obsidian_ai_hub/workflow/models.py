"""Workflow graph primitives: statuses, JSON Schema subset, typed references.

This module is pure (no DB, no adapters) so the store, validation, engine and
tests all share one definition of statuses, condition operators and reference
grammar. See ``docs/workflow/specification.md`` for the contract.
"""

from __future__ import annotations

import calendar
import copy
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NODE_TYPES: tuple[str, ...] = (
    "capability",
    "agent",
    "llm",
    "loop",
    "terminal",
    "loop_result",
    "text_template",
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
    "cancelling": frozenset(
        {"cancelled", "failed", "interrupted", "waiting_attention"}
    ),
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
MAX_EDGES = 60
MAX_ITERATIONS = 50
MAX_SCHEMA_DEPTH = 8

REF_KEY = "$ref"
EXPR_KEY = "$expr"

EXPR_KIND_DATE_MATH = "date_math"
EXPR_VERSION = 1
EXPR_KINDS = (EXPR_KIND_DATE_MATH,)
EXPR_RESULTS = ("date", "datetime")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_WEEK_START = "monday"

PIPE_KEY = "pipe"
MAX_PIPE_OPS = 20
PIPE_OPS: tuple[str, ...] = (
    "upper",
    "lower",
    "truncate",
    "slice",
    "replace",
    "pluck",
    "join",
    "default",
    "filter",
    "sort",
    "unique",
)

_FILTER_OPS: tuple[str, ...] = (
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "exists",
)
_FILTER_COMPARISON_OPS: frozenset[str] = frozenset(
    {"eq", "ne", "gt", "gte", "lt", "lte"}
)
_FILTER_AS_VALUES: tuple[str, ...] = ("auto", "date")
TEXT_OUTPUT_KEY = "text"

_DATE_MATH_TOKEN_RE = re.compile(r"(?P<op>[/+\-])(?P<amount>\d*)(?P<unit>[yMwdhms])")

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
    "minItems",
    "maxItems",
    "pattern",
    "format",
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
_SUPPORTED_FORMATS = ("date", "date-time")


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
    fmt = schema.get("format")
    if fmt is not None:
        if stype not in (None, "string"):
            errors.append(f"{path}.format: string 型にのみ指定できます")
        elif fmt not in _SUPPORTED_FORMATS:
            errors.append(
                f"{path}.format: {list(_SUPPORTED_FORMATS)} のいずれかが必要です"
            )
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
        for key in ("minItems", "maxItems"):
            limit = schema.get(key)
            if limit is not None and (
                isinstance(limit, bool) or not isinstance(limit, int) or limit < 0
            ):
                errors.append(f"{path}.{key}: 非負整数が必要です")
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if (
            isinstance(min_items, int)
            and not isinstance(min_items, bool)
            and isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and min_items > max_items
        ):
            errors.append(f"{path}: minItems は maxItems 以下である必要があります")
    return errors


def validate_value_against_schema(
    value: Any,
    schema: Any,
    *,
    path: str = "value",
    allow_expressions: bool = False,
    anchor_scope: str = "context",
) -> list[str]:
    """Validate ``value`` against the v1 schema subset; returns error strings.

    When ``allow_expressions`` is true a ``{"$expr": ...}`` leaf is validated as
    a typed value (shape + result type against the field schema) instead of
    being rejected as a plain object. This is only enabled for Run inputs;
    stored Agent/Capability outputs must never be interpreted as expressions.
    """
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    if allow_expressions and is_expression(value):
        return validate_expression(
            value,
            path=path,
            expected_type=schema.get("type"),
            expected_format=schema.get("format"),
            anchor_scope=anchor_scope,
        )
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
                        value[name],
                        sub,
                        path=f"{path}.{name}",
                        allow_expressions=allow_expressions,
                        anchor_scope=anchor_scope,
                    )
                )
    elif stype == "array":
        if not isinstance(value, list):
            return [f"{path}: array が必要です"]
        min_items = schema.get("minItems")
        if (
            isinstance(min_items, int)
            and not isinstance(min_items, bool)
            and len(value) < min_items
        ):
            errors.append(f"{path}: 要素数が minItems ({min_items}) 未満です")
        max_items = schema.get("maxItems")
        if (
            isinstance(max_items, int)
            and not isinstance(max_items, bool)
            and len(value) > max_items
        ):
            errors.append(f"{path}: 要素数が maxItems ({max_items}) を超えています")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(
                    validate_value_against_schema(
                        item,
                        items,
                        path=f"{path}[{index}]",
                        allow_expressions=allow_expressions,
                        anchor_scope=anchor_scope,
                    )
                )
    elif stype == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: string が必要です")
        else:
            errors.extend(_format_value_errors(value, schema.get("format"), path))
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


def apply_schema_defaults(value: Any, schema: Any) -> Any:
    """Fill object defaults declared in the v1 schema subset.

    Only object properties are filled, recursively for nested objects. Present
    keys are never overwritten, so ``$ref`` / ``$expr`` leaves and explicit
    values keep their meaning. Array items are not filled. Returns a new value;
    the input is not mutated.
    """
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return value
    if not isinstance(value, dict):
        return value
    if reference_path(value) is not None or is_expression(value):
        return value
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return value
    result = dict(value)
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            continue
        if name not in result:
            if "default" in prop:
                result[name] = copy.deepcopy(prop["default"])
            elif prop.get("type") == "object":
                nested = apply_schema_defaults({}, prop)
                if nested:
                    result[name] = nested
            continue
        if (
            prop.get("type") == "object"
            and isinstance(result[name], dict)
            and reference_path(result[name]) is None
            and not is_expression(result[name])
        ):
            result[name] = apply_schema_defaults(result[name], prop)
    return result


_DATE_VALUE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _format_value_errors(value: str, fmt: Any, path: str) -> list[str]:
    if fmt == "date":
        if not _DATE_VALUE_RE.match(value):
            return [f"{path}: format 'date' は YYYY-MM-DD が必要です"]
        try:
            date.fromisoformat(value)
        except ValueError:
            return [f"{path}: '{value}' は有効な日付ではありません"]
    elif fmt == "date-time":
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return [f"{path}: format 'date-time' は ISO 8601 が必要です"]
        if parsed.tzinfo is None:
            return [f"{path}: format 'date-time' にはタイムゾーンオフセットが必要です"]
    return []


def is_reference(value: Any) -> bool:
    """True when ``value`` is exactly ``{"$ref": "<path>"}``."""
    return (
        isinstance(value, dict)
        and set(value.keys()) == {REF_KEY}
        and isinstance(value.get(REF_KEY), str)
        and bool(value[REF_KEY].strip())
    )


def is_piped_reference(value: Any) -> bool:
    """True when ``value`` is ``{"$ref": "<path>", "pipe": [...]}``."""
    if not isinstance(value, dict) or PIPE_KEY not in value:
        return False
    if set(value.keys()) != {REF_KEY, PIPE_KEY}:
        return False
    ref = value.get(REF_KEY)
    return isinstance(ref, str) and bool(ref.strip()) and isinstance(
        value.get(PIPE_KEY), list
    )


def reference_path(value: Any) -> Optional[str]:
    """Return the ``$ref`` path of a bare or piped reference, else ``None``."""
    if is_reference(value):
        return str(value[REF_KEY])
    if is_piped_reference(value):
        return str(value[REF_KEY])
    return None


def reference_pipe(value: Any) -> list[Any]:
    """Return the pipe ops of a piped reference, else an empty list."""
    if is_piped_reference(value):
        return list(value[PIPE_KEY])
    return []


def iter_references(value: Any) -> Iterable[str]:
    """Yield every ``$ref`` string contained in a nested config value.

    Piped references yield their path and are not descended into (pipe args
    must not contain further references).
    """
    path = reference_path(value)
    if path is not None:
        yield path
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_references(child)


def iter_piped_reference_entries(value: Any) -> Iterable[tuple[str, list[Any]]]:
    """Yield ``(ref_path, pipe)`` for every piped reference in a nested value."""
    if is_piped_reference(value):
        yield str(value[REF_KEY]), list(value[PIPE_KEY])
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_piped_reference_entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_piped_reference_entries(child)


def iter_invalid_reference_shapes(value: Any) -> Iterable[dict[str, Any]]:
    """Yield dicts that carry ``$ref``/``$expr`` but do not match the grammar.

    A malformed reference (e.g. ``{"$ref": ..., "pipe": "upper"}``) otherwise
    matches neither :func:`is_reference` nor :func:`is_piped_reference`, so it
    would be silently passed through as a literal.
    """
    if isinstance(value, dict):
        if REF_KEY in value and not (is_reference(value) or is_piped_reference(value)):
            yield value
        if EXPR_KEY in value and not is_expression(value):
            yield value
        for child in value.values():
            yield from iter_invalid_reference_shapes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_invalid_reference_shapes(child)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_pipe(pipe: Any, *, path: str = "pipe") -> list[str]:
    """Validate a pipe op list (shape, operator, argument keys/types/ranges)."""
    errors: list[str] = []
    if not isinstance(pipe, list):
        return [f"{path}: 配列が必要です"]
    if not pipe:
        return [f"{path}: 1 つ以上の演算子が必要です"]
    if len(pipe) > MAX_PIPE_OPS:
        return [f"{path}: 演算子は最大 {MAX_PIPE_OPS} 個です"]
    for index, step in enumerate(pipe):
        step_path = f"{path}[{index}]"
        if not isinstance(step, dict):
            errors.append(f"{step_path}: object が必要です")
            continue
        unknown = set(step.keys()) - {"op", "args"}
        if unknown:
            errors.append(f"{step_path}: 未知のキー {sorted(unknown)}")
        op = step.get("op")
        if op not in PIPE_OPS:
            errors.append(f"{step_path}.op: {list(PIPE_OPS)} のいずれかが必要です")
            continue
        args = step.get("args", {})
        if not isinstance(args, dict):
            errors.append(f"{step_path}.args: object が必要です")
            continue
        if _contains_reference_or_expression(args):
            errors.append(f"{step_path}.args: 引数に $ref / $expr は使えません")
        errors.extend(_validate_pipe_args(op, args, path=step_path))
    return errors


def _contains_reference_or_expression(value: Any) -> bool:
    if reference_path(value) is not None or is_expression(value):
        return True
    if isinstance(value, dict):
        return any(_contains_reference_or_expression(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_reference_or_expression(v) for v in value)
    return False


def _validate_pipe_args(op: str, args: dict[str, Any], *, path: str) -> list[str]:
    errors: list[str] = []

    def unknown(allowed: set[str]) -> None:
        extra = set(args.keys()) - allowed
        if extra:
            errors.append(f"{path}.args: 未知の引数 {sorted(extra)}")

    if op in ("upper", "lower"):
        unknown(set())
    elif op == "truncate":
        unknown({"max_len"})
        max_len = args.get("max_len")
        if not _is_int(max_len) or max_len < 0:
            errors.append(f"{path}.args.max_len: 0 以上の整数が必要です")
    elif op == "slice":
        unknown({"limit", "offset"})
        limit = args.get("limit")
        if not _is_int(limit) or limit < 0:
            errors.append(f"{path}.args.limit: 0 以上の整数が必要です")
        offset = args.get("offset")
        if offset is not None and (not _is_int(offset) or offset < 0):
            errors.append(f"{path}.args.offset: 0 以上の整数が必要です")
    elif op == "replace":
        unknown({"frm", "to"})
        frm = args.get("frm")
        if not isinstance(frm, str) or frm == "":
            errors.append(f"{path}.args.frm: 空でない文字列が必要です")
        to = args.get("to")
        if to is not None and not isinstance(to, str):
            errors.append(f"{path}.args.to: 文字列が必要です")
    elif op == "pluck":
        unknown({"key"})
        key = args.get("key")
        if not isinstance(key, str) or key == "":
            errors.append(f"{path}.args.key: 空でない文字列が必要です")
    elif op == "join":
        unknown({"sep"})
        sep = args.get("sep")
        if sep is not None and not isinstance(sep, str):
            errors.append(f"{path}.args.sep: 文字列が必要です")
    elif op == "default":
        unknown({"value"})
        if "value" not in args:
            errors.append(f"{path}.args.value: value が必要です")
    elif op == "filter":
        unknown({"key", "op", "value", "as"})
        key = args.get("key")
        if not isinstance(key, str) or key == "":
            errors.append(f"{path}.args.key: 空でない文字列が必要です")
        predicate = args.get("op", "eq")
        if predicate not in _FILTER_OPS:
            errors.append(
                f"{path}.args.op: {list(_FILTER_OPS)} のいずれかが必要です"
            )
            predicate = None
        if predicate == "exists":
            if "value" in args:
                errors.append(
                    f"{path}.args.value: op 'exists' では指定できません"
                )
        elif predicate is not None and "value" not in args:
            errors.append(f"{path}.args.value: value が必要です")
        as_value = args.get("as")
        if as_value is not None:
            if as_value not in _FILTER_AS_VALUES:
                errors.append(
                    f"{path}.args.as: {list(_FILTER_AS_VALUES)} のいずれかが必要です"
                )
            elif predicate is not None and predicate not in _FILTER_COMPARISON_OPS:
                errors.append(
                    f"{path}.args.as: op 'eq'/'ne'/'gt'/'gte'/'lt'/'lte' でのみ指定できます"
                )
        if (
            predicate in ("in", "not_in")
            and "value" in args
            and not isinstance(args["value"], list)
        ):
            errors.append(
                f"{path}.args.value: op '{predicate}' では配列が必要です"
            )
        if predicate == "contains" and "value" in args:
            if not isinstance(args["value"], str):
                errors.append(
                    f"{path}.args.value: op 'contains' では文字列が必要です"
                )
    elif op == "sort":
        unknown({"key", "order"})
        key = args.get("key")
        if key is not None and (not isinstance(key, str) or key == ""):
            errors.append(f"{path}.args.key: 空でない文字列が必要です")
        order = args.get("order")
        if order is not None and order not in ("asc", "desc"):
            errors.append(f"{path}.args.order: 'asc' / 'desc' が必要です")
    elif op == "unique":
        unknown({"key"})
        key = args.get("key")
        if key is not None and (not isinstance(key, str) or key == ""):
            errors.append(f"{path}.args.key: 空でない文字列が必要です")
    return errors


def _stringify_pipe_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_pipe_string(value: Any, op: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"pipe '{op}' は文字列にのみ適用できます")
    return value


def _as_pipe_list(value: Any, op: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"pipe '{op}' は配列にのみ適用できます")
    return value


def _pipe_equals(left: Any, right: Any) -> bool:
    """Equality that never conflates ``bool`` with ``int``/``float``."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return bool(left == right)


def _pipe_identity(value: Any) -> str:
    import json

    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _parse_pipe_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(
            "pipe 'filter': as 'date' には ISO 8601 日時文字列が必要です"
        )
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "pipe 'filter': as 'date' の値は ISO 8601 日時文字列である必要があります"
        ) from exc


def _filter_date_compare(actual: Any, expected: Any, predicate: str) -> bool:
    left = _parse_pipe_datetime(actual)
    right = _parse_pipe_datetime(expected)
    if (left.tzinfo is None) != (right.tzinfo is None):
        raise ValueError(
            "pipe 'filter': as 'date' はタイムゾーンの有無を揃えてください"
        )
    if predicate == "eq":
        return left == right
    if predicate == "ne":
        return left != right
    if predicate == "gt":
        return left > right
    if predicate == "gte":
        return left >= right
    if predicate == "lt":
        return left < right
    return left <= right


def _filter_auto_compare(actual: Any, expected: Any, predicate: str) -> bool:
    if predicate in ("eq", "ne"):
        equal = _pipe_equals(actual, expected)
        return equal if predicate == "eq" else not equal
    if predicate in ("gt", "gte", "lt", "lte"):
        both_numbers = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        )
        both_strings = isinstance(actual, str) and isinstance(expected, str)
        if not (both_numbers or both_strings):
            return False
        if predicate == "gt":
            return actual > expected
        if predicate == "gte":
            return actual >= expected
        if predicate == "lt":
            return actual < expected
        return actual <= expected
    return False


def _pipe_predicate(
    item: Any, key: str, predicate: str, expected: Any, *, as_date: bool
) -> bool:
    if predicate == "exists":
        return isinstance(item, dict) and key in item
    if not isinstance(item, dict) or key not in item:
        return False
    actual = item[key]
    if predicate == "in":
        return any(_pipe_equals(actual, candidate) for candidate in expected)
    if predicate == "not_in":
        return not any(_pipe_equals(actual, candidate) for candidate in expected)
    if predicate == "contains":
        if isinstance(actual, str):
            return isinstance(expected, str) and expected in actual
        if isinstance(actual, list):
            return any(_pipe_equals(element, expected) for element in actual)
        return False
    if as_date:
        if actual is None:
            return False
        return _filter_date_compare(actual, expected, predicate)
    return _filter_auto_compare(actual, expected, predicate)


def _sort_pipe_items(
    items: list[Any], values: list[Any], order: str
) -> list[Any]:
    non_null = [v for v in values if v is not None]
    if non_null:
        if all(isinstance(v, bool) for v in non_null):
            pass
        elif all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null
        ):
            pass
        elif all(isinstance(v, str) for v in non_null):
            pass
        else:
            raise ValueError("pipe 'sort': 要素の型を揃えてください")
    paired = [
        (value, item) for value, item in zip(values, items) if value is not None
    ]
    paired.sort(key=lambda pair: pair[0], reverse=(order == "desc"))
    ordered = [item for _, item in paired]
    ordered.extend(item for value, item in zip(values, items) if value is None)
    return ordered


def apply_pipe(value: Any, pipe: list[Any]) -> Any:
    """Apply pipe ops left-to-right; raises ``ValueError`` on type mismatch."""
    current = value
    for step in pipe:
        op = step.get("op")
        args = step.get("args") or {}
        if op in ("upper", "lower"):
            text = _as_pipe_string(current, op)
            current = text.upper() if op == "upper" else text.lower()
        elif op == "truncate":
            text = _as_pipe_string(current, op)
            current = text[: int(args["max_len"])]
        elif op == "slice":
            limit = int(args["limit"])
            offset = int(args.get("offset") or 0)
            if isinstance(current, str):
                current = current[offset : offset + limit]
            elif isinstance(current, list):
                current = current[offset : offset + limit]
            else:
                raise ValueError("pipe 'slice' は文字列または配列にのみ適用できます")
        elif op == "replace":
            text = _as_pipe_string(current, op)
            current = text.replace(str(args["frm"]), str(args.get("to") or ""))
        elif op == "pluck":
            items = _as_pipe_list(current, op)
            key = str(args["key"])
            plucked: list[Any] = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("pipe 'pluck' は object 配列にのみ適用できます")
                if key not in item:
                    raise ValueError(f"pipe 'pluck': キー '{key}' が要素にありません")
                plucked.append(item[key])
            current = plucked
        elif op == "join":
            items = _as_pipe_list(current, op)
            sep = str(args.get("sep") or "")
            current = sep.join(_stringify_pipe_value(item) for item in items)
        elif op == "default":
            if current is None or current == "" or (
                isinstance(current, list) and not current
            ):
                current = args.get("value")
        elif op == "filter":
            items = _as_pipe_list(current, op)
            key = str(args["key"])
            predicate = str(args.get("op") or "eq")
            expected = args.get("value")
            as_date = args.get("as") == "date"
            current = [
                item
                for item in items
                if _pipe_predicate(
                    item, key, predicate, expected, as_date=as_date
                )
            ]
        elif op == "sort":
            items = _as_pipe_list(current, op)
            key = args.get("key")
            order = str(args.get("order") or "asc")
            values: list[Any] = []
            for item in items:
                if key is None:
                    values.append(item)
                else:
                    if not isinstance(item, dict) or key not in item:
                        raise ValueError(
                            f"pipe 'sort': キー '{key}' が要素にありません"
                        )
                    values.append(item[key])
            current = _sort_pipe_items(items, values, order)
        elif op == "unique":
            items = _as_pipe_list(current, op)
            key = args.get("key")
            seen: set[str] = set()
            deduped: list[Any] = []
            for item in items:
                if key is None:
                    identity = _pipe_identity(item)
                else:
                    if not isinstance(item, dict) or key not in item:
                        raise ValueError(
                            f"pipe 'unique': キー '{key}' が要素にありません"
                        )
                    identity = _pipe_identity(item[key])
                if identity in seen:
                    continue
                seen.add(identity)
                deduped.append(item)
            current = deduped
        else:  # pragma: no cover - validate_pipe rejects unknown ops first
            raise ValueError(f"未対応の pipe 演算子です: {op}")
    return current


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


def is_expression(value: Any) -> bool:
    """True when ``value`` is exactly ``{"$expr": {...}}``."""
    return (
        isinstance(value, dict)
        and set(value.keys()) == {EXPR_KEY}
        and isinstance(value.get(EXPR_KEY), dict)
    )


def iter_expressions(value: Any) -> Iterable[dict[str, Any]]:
    """Yield every inner ``$expr`` object contained in a nested config value."""
    if is_expression(value):
        yield value[EXPR_KEY]
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_expressions(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_expressions(child)


def parse_date_math(math: str) -> list[tuple[str, Optional[int], str]]:
    """Parse a compact date-math string into ordered ``(op, amount, unit)``.

    Grammar: ``(("+"|"-") digits unit | "/" unit)*`` with units
    ``y M w d h m s`` (case sensitive). Raises ``ValueError`` on any unknown
    operator, unit or stray character.
    """
    ops: list[tuple[str, Optional[int], str]] = []
    position = 0
    for match in _DATE_MATH_TOKEN_RE.finditer(math):
        if match.start() != position:
            raise ValueError(f"日時式の構文が不正です: '{math[position:match.start()]}'")
        position = match.end()
        op = match.group("op")
        amount_text = match.group("amount")
        unit = match.group("unit")
        if op == "/":
            if amount_text:
                raise ValueError("'/' には数値を付けられません")
            ops.append((op, None, unit))
        else:
            if amount_text == "":
                raise ValueError(f"'{op}{unit}' には数値が必要です")
            ops.append((op, int(amount_text), unit))
    if position != len(math):
        raise ValueError(f"日時式の構文が不正です: '{math[position:]}'")
    return ops


def _valid_timezone(name: Any) -> bool:
    if not isinstance(name, str) or not name:
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return False
    return True


def _parse_reference_time(value: Any) -> datetime:
    """Coerce a stored/derived reference time into an aware datetime.

    Naive datetimes (including the scheduler's JST fire slots) are anchored to
    the configured default timezone and then treated as absolute instants.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"基準時刻を解釈できません: {value!r}") from exc
    else:
        raise ValueError(f"基準時刻を解釈できません: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
    return dt


def normalize_reference_time(value: Any) -> Optional[str]:
    """Normalize a reference-time input to a UTC ISO string (or None)."""
    if value is None:
        return None
    return _parse_reference_time(value).astimezone(timezone.utc).isoformat()


def validate_expression(
    value: Any,
    *,
    path: str = "value",
    expected_type: Optional[str] = None,
    expected_format: Optional[str] = None,
    anchor_scope: str = "full",
    anchor_type_resolver: Optional[Any] = None,
) -> list[str]:
    """Validate a ``{"$expr": ...}`` date-math value.

    ``expected_type``/``expected_format`` are the target field's schema (when
    known). ``anchor_scope='context'`` restricts anchors to the Run context
    (used for Run inputs); ``'full'`` allows typed Node/Loop references.
    ``anchor_type_resolver(ref)`` returns ``(type, format)`` or ``None`` when
    the referenced field's declared type is unknown.
    """
    if not is_expression(value):
        return [f"{path}: $expr は object である必要があります"]
    expr = value[EXPR_KEY]
    errors: list[str] = []
    allowed = {
        "kind",
        "version",
        "anchor",
        "math",
        "timezone",
        "week_starts_on",
        "result",
    }
    for key in expr:
        if key not in allowed:
            errors.append(f"{path}.$expr: 未知のキー '{key}'")
    if expr.get("kind") not in EXPR_KINDS:
        errors.append(f"{path}.$expr.kind: 'date_math' が必要です")
    if expr.get("version") != EXPR_VERSION:
        errors.append(f"{path}.$expr.version: {EXPR_VERSION} が必要です")

    anchor = expr.get("anchor")
    if anchor == "now":
        pass
    elif is_reference(anchor):
        ref = str(anchor[REF_KEY])
        if anchor_scope == "context":
            if ref != "run.context.reference_time":
                errors.append(
                    f"{path}.$expr.anchor: Run 入力では now または "
                    "run.context.reference_time のみ参照できます"
                )
        elif anchor_type_resolver is not None:
            resolved = anchor_type_resolver(ref)
            if resolved is not None:
                _, fmt = resolved
                if fmt not in ("date", "date-time"):
                    errors.append(
                        f"{path}.$expr.anchor: '{ref}' は date/date-time 型ではありません"
                    )
    else:
        errors.append(f"{path}.$expr.anchor: 'now' または型付き参照が必要です")

    math = expr.get("math")
    if math is not None:
        if not isinstance(math, str):
            errors.append(f"{path}.$expr.math: 文字列が必要です")
        else:
            try:
                parse_date_math(math)
            except ValueError as exc:
                errors.append(f"{path}.$expr.math: {exc}")

    timezone_name = expr.get("timezone")
    if timezone_name is not None and not _valid_timezone(timezone_name):
        errors.append(f"{path}.$expr.timezone: 不正なタイムゾーンです")

    week_start = expr.get("week_starts_on")
    if week_start is not None and week_start not in WEEKDAYS:
        errors.append(f"{path}.$expr.week_starts_on: {list(WEEKDAYS)} のいずれかが必要です")

    result = expr.get("result")
    if result not in EXPR_RESULTS:
        errors.append(f"{path}.$expr.result: {list(EXPR_RESULTS)} のいずれかが必要です")
    else:
        if expected_type is not None and expected_type != "string":
            errors.append(f"{path}: $expr は string 型の項目にのみ指定できます")
        elif expected_format == "date" and result != "date":
            errors.append(f"{path}: format 'date' には result 'date' が必要です")
        elif expected_format == "date-time" and result != "datetime":
            errors.append(f"{path}: format 'date-time' には result 'datetime' が必要です")
    return errors


def _coerce_anchor(value: Any, tz: ZoneInfo) -> datetime:
    return _parse_reference_time(value).astimezone(tz)


def _add_months(dt: datetime, months: int, tz: ZoneInfo) -> datetime:
    naive = dt.replace(tzinfo=None)
    total = naive.month - 1 + months
    year = naive.year + total // 12
    month = total % 12 + 1
    day = min(naive.day, calendar.monthrange(year, month)[1])
    return naive.replace(year=year, month=month, day=day).replace(tzinfo=tz)


def _floor(dt: datetime, unit: str, week_start: str) -> datetime:
    naive = dt.replace(tzinfo=None)
    if unit == "y":
        naive = naive.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    elif unit == "M":
        naive = naive.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif unit == "w":
        start_index = WEEKDAYS.index(week_start)
        delta = (naive.weekday() - start_index) % 7
        naive = (naive - timedelta(days=delta)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif unit == "d":
        naive = naive.replace(hour=0, minute=0, second=0, microsecond=0)
    elif unit == "h":
        naive = naive.replace(minute=0, second=0, microsecond=0)
    elif unit == "m":
        naive = naive.replace(second=0, microsecond=0)
    elif unit == "s":
        naive = naive.replace(microsecond=0)
    return naive.replace(tzinfo=dt.tzinfo)


def evaluate_expression(
    value: Any,
    *,
    reference_time: Any,
    run_inputs: dict[str, Any],
    node_outputs: dict[str, Any],
    loop_state: Optional[dict[str, Any]] = None,
    loop_input: Optional[dict[str, Any]] = None,
    loop_iteration: Optional[int] = None,
) -> str:
    """Evaluate a date-math expression to a date or datetime string.

    Raises ``ValueError`` when the expression or its anchor cannot be resolved
    so callers fail the node before any external side effect.
    """
    if not is_expression(value):
        raise ValueError("$expr が不正です")
    expr = value[EXPR_KEY]
    timezone_name = expr.get("timezone") or DEFAULT_TIMEZONE
    try:
        tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError(f"不正なタイムゾーンです: {timezone_name}") from exc
    week_start = expr.get("week_starts_on") or DEFAULT_WEEK_START

    anchor = expr.get("anchor")
    if anchor == "now":
        dt = _parse_reference_time(reference_time)
    elif is_reference(anchor):
        raw = resolve_reference(
            anchor[REF_KEY],
            run_inputs=run_inputs,
            node_outputs=node_outputs,
            loop_state=loop_state,
            loop_input=loop_input,
            loop_iteration=loop_iteration,
            reference_time=reference_time,
        )
        dt = _coerce_anchor(raw, tz)
    else:
        raise ValueError("$expr.anchor が不正です")
    dt = dt.astimezone(tz)

    try:
        for op, amount, unit in parse_date_math(expr.get("math") or ""):
            if op == "/":
                dt = _floor(dt, unit, week_start)
                continue
            sign = 1 if op == "+" else -1
            assert amount is not None
            count = sign * amount
            if unit == "y":
                dt = _add_months(dt, count * 12, tz)
            elif unit == "M":
                dt = _add_months(dt, count, tz)
            elif unit == "w":
                naive = dt.replace(tzinfo=None) + timedelta(days=count * 7)
                dt = naive.replace(tzinfo=tz)
            elif unit == "d":
                naive = dt.replace(tzinfo=None) + timedelta(days=count)
                dt = naive.replace(tzinfo=tz)
            elif unit in ("h", "m", "s"):
                # ``h``/``m``/``s`` are elapsed time, so apply on the absolute
                # timeline (a DST-aware ``dt + timedelta`` is wall-clock math).
                seconds = count * {"h": 3600, "m": 60, "s": 1}[unit]
                dt = (
                    dt.astimezone(timezone.utc) + timedelta(seconds=seconds)
                ).astimezone(tz)
    except OverflowError as exc:
        raise ValueError(f"日時式の演算結果が範囲外です: {exc}") from exc

    if expr.get("result") == "date":
        return dt.strftime("%Y-%m-%d")
    return dt.isoformat()


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
    reference_time: Optional[str] = None,
) -> Any:
    """Resolve a typed reference to its current value.

    Raises ``KeyError`` when a path component is missing so the caller can
    fail the node before any external side effect.
    """
    segments = _path_segments(ref)
    if not segments:
        raise KeyError("空の参照は解決できません")
    head = segments[0]
    if head == "run" and len(segments) == 3 and segments[1] == "context":
        if segments[2] == "reference_time":
            if reference_time is None:
                raise KeyError("run.context.reference_time が設定されていません")
            return reference_time
        raise KeyError(f"未対応の run.context 参照です: {ref}")
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
    reference_time: Optional[str] = None,
) -> Any:
    """Resolve references (with optional pipe) and date expressions."""
    path = reference_path(value)
    if path is not None:
        resolved = resolve_reference(
            path,
            run_inputs=run_inputs,
            node_outputs=node_outputs,
            loop_state=loop_state,
            loop_input=loop_input,
            loop_iteration=loop_iteration,
            reference_time=reference_time,
        )
        pipe = reference_pipe(value)
        return apply_pipe(resolved, pipe) if pipe else resolved
    if is_expression(value):
        return evaluate_expression(
            value,
            reference_time=reference_time,
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
                reference_time=reference_time,
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
                reference_time=reference_time,
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

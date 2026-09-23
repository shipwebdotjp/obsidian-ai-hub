"""Sandboxed Jinja2 rendering for the ``text_template`` workflow node.

The template is authored by the workflow designer (a human) while its variables
come from upstream Node outputs, so the renderer uses Jinja2's
``SandboxedEnvironment`` (no loader, no custom globals, ``StrictUndefined``) and
enforces size limits on both the template body and the rendered output. See
``docs/workflow/specification.md`` §3.8.
"""

from __future__ import annotations

from typing import Any, Iterable

from jinja2 import StrictUndefined, TemplateError
from jinja2.meta import find_referenced_templates, find_undeclared_variables
from jinja2.sandbox import SandboxedEnvironment

TEMPLATE_MAX_BYTES = 16 * 1024
TEMPLATE_OUTPUT_MAX_BYTES = 64 * 1024


# The environment is immutable/stateless here, so one instance is reused.
_ENV = SandboxedEnvironment(
    undefined=StrictUndefined,
    loader=None,
    autoescape=False,
)


def validate_template(
    template: Any,
    *,
    allowed_variables: Iterable[str],
    path: str = "template",
) -> list[str]:
    """Validate template syntax, size and that all variables are provided."""
    if not isinstance(template, str):
        return [f"{path}: 文字列が必要です"]
    if len(template.encode("utf-8")) > TEMPLATE_MAX_BYTES:
        return [
            f"{path}: テンプレート本文が上限 {TEMPLATE_MAX_BYTES} bytes を超えています"
        ]
    try:
        ast = _ENV.parse(template)
    except TemplateError as exc:
        return [f"{path}: Jinja2 構文エラー: {exc}"]
    if any(True for _ in find_referenced_templates(ast)):
        return [f"{path}: include / extends / import は使えません（loader なし）"]
    unknown = sorted(
        find_undeclared_variables(ast)
        - set(allowed_variables)
        - set(_ENV.globals)
    )
    if unknown:
        return [f"{path}: 未定義の変数 {unknown} が inputs にありません"]
    return []


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Render ``template`` with ``variables``; raises ``ValueError`` on failure.

    The output size limit is enforced after rendering (Jinja2 does not expose a
    stream bounded by bytes), so a pathological template can still allocate
    before the check trips; the limit bounds what is persisted and passed on.
    """
    if not isinstance(template, str):
        raise ValueError("template は文字列が必要です")
    if len(template.encode("utf-8")) > TEMPLATE_MAX_BYTES:
        raise ValueError(
            f"テンプレート本文が上限 {TEMPLATE_MAX_BYTES} bytes を超えています"
        )
    try:
        # Positional mapping avoids a ``self`` keyword collision for an input
        # literally named ``self`` (``render(**variables)`` would raise).
        rendered = _ENV.from_string(template).render(variables)
    except Exception as exc:  # noqa: BLE001 - surfaced as a node failure
        raise ValueError(f"テンプレートの描画に失敗しました: {exc}") from exc
    if len(rendered.encode("utf-8")) > TEMPLATE_OUTPUT_MAX_BYTES:
        raise ValueError(
            f"テンプレート出力が上限 {TEMPLATE_OUTPUT_MAX_BYTES} bytes を超えています"
        )
    return rendered

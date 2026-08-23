"""Safe, shared LLM-tool catalog and allowlist for configurable agents.

This module is the only tool-resolution entry point for user-configurable or
otherwise general-purpose agents.  Callers persist and select stable tool IDs,
then use :func:`resolve_tools` to obtain only the explicitly approved
``BaseTool`` adapters.

``handler`` modules implement lower-level integrations and can include direct
external side effects used by HITL handlers or Planner promotion.  They are not
an agent-tool catalog: never expose a handler merely because it is decorated
with ``@tool``.  Fixed internal workflows, such as web research, may import a
small, compile-time read-only tool set directly when that narrower contract is
part of the workflow.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from obsidian_ai_hub.calendar.hitl import register_calendar_event_approval
from obsidian_ai_hub.handler.obsidian_vault_retriever import search_obsidian_vault
from obsidian_ai_hub.handler.web_extract import web_extract
from obsidian_ai_hub.handler.web_search import web_search
from obsidian_ai_hub.planner.apple import (
    fetch_calendar_events,
    fetch_incomplete_reminders,
)
from obsidian_ai_hub.reminders.hitl import register_reminder_approval
from obsidian_ai_hub.web.services.vault import get_vault_file

logger = logging.getLogger(__name__)

# Plugin tools: user-supplied ``BaseTool`` adapters loaded from
# ``~/.config/obsidian-ai-hub/plugins/tools/*.py`` (configurable via
# ``OBSIDIAN_AI_HUB_PLUGINS_DIR`` / ``plugins.tools_dir``).
# Each plugin file must expose either a ``register() -> dict`` function or a
# module-level ``TOOL_DEFINITIONS`` dict with the same shape as
# ``_BUILTIN_TOOL_DEFINITIONS``.  Plugin ``tool_id`` values must be prefixed
# with ``custom:`` (auto-prefixed if omitted) so built-ins can never be
# shadowed.
PLUGIN_TOOL_ID_PREFIX = "custom:"
_PLUGIN_TOOL_ID_RE = r"^custom:[a-z0-9][a-z0-9_-]{0,63}$"
_BUILTIN_TOOL_IDS: set[str] = set()  # populated after _BUILTIN_TOOL_DEFINITIONS
_PLUGIN_TOOL_ID_RE_COMPILED = re.compile(_PLUGIN_TOOL_ID_RE)

EXPECTED_TOOL_EXCEPTIONS = (
    FileNotFoundError,
    ValueError,
    KeyError,
    TypeError,
    PermissionError,
)

ALLOWED_MEMORY_KINDS = (
    "preference",
    "decision_policy",
    "fact",
    "commitment",
    "pattern",
    "episode",
)
_MEMORY_KEY_PATTERN = r"^[a-z0-9-]{1,64}$"

_RECURRING_TZ = ZoneInfo("Asia/Tokyo")


def _recurring_to_calendar_events(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert recurring expand items (kind==event) to calendar event dicts."""
    out: List[Dict[str, Any]] = []
    for item in items:
        if item.get("kind") != "event":
            continue
        title = str(item.get("title") or "")
        if not title:
            continue
        if item.get("all_day"):
            # all-day: midnight JST on that date
            d = item.get("date")
            if not isinstance(d, date):
                continue
            start_iso = datetime.combine(d, time.min).replace(tzinfo=_RECURRING_TZ).isoformat()
            end_iso = datetime.combine(d, time.min).replace(tzinfo=_RECURRING_TZ).isoformat()
            out.append(
                {
                    "title": title,
                    "all_day": True,
                    "start": start_iso,
                    "end": end_iso,
                    "source": "recurring",
                }
            )
        else:
            start_iso = item.get("start_time")
            if not start_iso:
                continue
            out.append(
                {
                    "title": title,
                    "start": start_iso,
                    "end": item.get("end_time"),
                    "all_day": False,
                    "source": "recurring",
                }
            )
    return out


def _recurring_to_reminders(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert recurring expand items (kind==task) to reminder dicts."""
    out: List[Dict[str, Any]] = []
    for item in items:
        if item.get("kind") != "task":
            continue
        title = str(item.get("title") or "")
        if not title:
            continue
        if item.get("all_day"):
            d = item.get("date")
            if not isinstance(d, date):
                continue
            # date-only for all-day tasks
            out.append({"title": title, "due": d.isoformat(), "source": "recurring"})
        else:
            # timed task: use start_time as due
            due = item.get("start_time")
            if not due:
                continue
            out.append({"title": title, "due": due, "source": "recurring"})
    return out


# --- Input Schemas ---


class VaultReadFileInput(BaseModel):
    relative_path: str = Field(
        description="Path to the markdown file relative to the Vault root (e.g. 'notes/daily.md')."
    )


class CalendarReadInput(BaseModel):
    start_date: str = Field(
        description="Start date in YYYY-MM-DD format (e.g. '2026-08-25'). Use the current date from system context to resolve relative dates like 'today'."
    )
    end_date: str = Field(
        description="End date in YYYY-MM-DD format (e.g. '2026-08-26'). Use the current date from system context."
    )
    calendar_name: Optional[str] = Field(
        default=None, description="Optional target calendar name."
    )


class RemindersReadInput(BaseModel):
    start_date: str = Field(
        description="Start date in YYYY-MM-DD format (e.g. '2026-08-25'). Use the current date from system context to resolve relative dates like 'today'."
    )
    end_date: str = Field(
        description="End date in YYYY-MM-DD format (e.g. '2026-08-26'). Use the current date from system context."
    )


class CalendarCreateProposalInput(BaseModel):
    title: str = Field(description="Title of the calendar event.")
    start_time: str = Field(
        description="Start time in ISO format (e.g. '2026-08-25T10:00:00+09:00')."
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End time in ISO format (e.g. '2026-08-25T11:00:00+09:00').",
    )
    location: Optional[str] = Field(default=None, description="Event location.")
    content: Optional[str] = Field(
        default=None,
        description="Detailed background, notes, or rationale for the event.",
    )


class ReminderCreateProposalInput(BaseModel):
    title: str = Field(description="Title of the reminder.")
    due_date: Optional[str] = Field(
        default=None,
        description="Due date in ISO format or YYYY-MM-DD (e.g. '2026-08-25').",
    )
    content: Optional[str] = Field(
        default=None,
        description="Detailed background, notes, or rationale for the reminder.",
    )


class MemorySearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description="検索クエリ。ユーザーの嗜好や事実に関するキーワードを日本語で要約（例: '返信の文体の好み'）。"
    )
    kind: Optional[Literal[
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    ]] = Field(
        default=None,
        description="絞り込み: preference|decision_policy|fact|commitment|pattern|episode のいずれか。",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="最大返却件数 (1-10)。省略時は5。",
    )


class MemoryProposeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        description="記憶する内容本文。日本語で1文、具体的かつ検証可能に（例: '朝会では結論から先に述べる簡潔な報告を好む'）。推測は不可。"
    )
    kind: Literal[
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    ] = Field(
        description="種別: preference|decision_policy|fact|commitment|pattern|episode のいずれか。"
    )
    memory_key: Optional[str] = Field(
        default=None,
        pattern=_MEMORY_KEY_PATTERN,
        description="任意の技術的キー（英数字とハイフンのみ、1-64文字）。省略時は空文字で保存。日本語の translit は行わない。",
    )
    topics: Optional[List[str]] = Field(
        default=None,
        description="既存トピック候補からのみ。なければ省略。例: ['ソフトウェア開発']",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="任意のタグ配列。省略可。",
    )
    evidence_quote: Optional[str] = Field(
        default=None,
        description="現在のユーザ発話からの引用。省略可。サーバが検証し、不一致なら発話全体を根拠として保存する。",
    )
    rationale: Optional[str] = Field(
        default=None,
        description="なぜ記憶すべきかの簡潔な理由。レビュー画面の provenance に保存される。",
    )


# --- Memory Tool Factories (require trusted context) ---


def _sanitize_unexpected_error(exc: Exception) -> str:
    """Return a generic, sanitized message for unexpected tool failures.

    Unexpected DB/IO errors can leak paths, SQL, or other internals. Keep
    detail in the server log (via logger.exception at the call site) and
    return a Japanese, user-safe message for the LLM/end user.
    """
    return "ツール実行中に予期しないエラーが発生しました。しばらく待って再試行してください。"


def _make_memory_search_tool(trusted_ctx: Optional[Dict[str, Any]] = None) -> BaseTool:
    """Create a memory_search tool. trusted_ctx is kept for symmetry but not required for read."""

    @tool(args_schema=MemorySearchInput)
    def memory_search(
        query: str, kind: Optional[str] = None, limit: int = 5
    ) -> str:
        """承認済み長期記憶（approved）を検索します。ユーザーの嗜好や過去の事実が関係する質問では、回答を生成する前に必ず本ツールを呼び出し、返却された content を根拠として回答に反映してください。結果が空ならその旨を述べて一般的な回答をしてください。推測で補完しないこと。"""
        try:
            from obsidian_ai_hub.memory.agent_tools import search_memories

            res = search_memories(query=query, kind=kind, limit=limit)
            return json.dumps(res, ensure_ascii=False)
        except ValueError as exc:
            logger.warning("memory_search validation failed: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        except Exception:
            logger.exception("memory_search failed")
            return json.dumps({"error": _sanitize_unexpected_error(Exception())}, ensure_ascii=False)

    # Give stable name for LLM tool calling (overrides function name)
    memory_search.name = "memory_search"  # type: ignore[attr-defined]
    return memory_search


def _make_memory_propose_tool(
    trusted_ctx: Optional[Dict[str, Any]] = None,
) -> BaseTool:
    """Create a memory_propose tool bound to a trusted execution context."""

    @tool(args_schema=MemoryProposeInput)
    def memory_propose(
        content: str,
        kind: str,
        memory_key: Optional[str] = None,
        topics: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        evidence_quote: Optional[str] = None,
        rationale: Optional[str] = None,
    ) -> str:
        """ユーザーが嗜好・事実・方針を明示した内容を長期記憶候補として保存します。推測で作成せず、ユーザーの発話に明確な根拠がある場合のみ呼び出してください。保存された候補はメモリ画面で人間が確認・編集・承認します。stability は自動的に tentative として保存されます。1ターンに1件まで。"""
        if trusted_ctx is None:
            return json.dumps(
                {"error": "memory_propose はエージェント実行コンテキストが無いため呼び出せません"},
                ensure_ascii=False,
            )
        try:
            from obsidian_ai_hub.memory.agent_tools import create_memory_candidate

            res = create_memory_candidate(
                content=content,
                kind=kind,
                memory_key=memory_key,
                topics=topics,
                tags=tags,
                evidence_quote=evidence_quote,
                rationale=rationale,
                trusted_ctx=trusted_ctx,
            )
            return json.dumps(res, ensure_ascii=False)
        except ValueError as exc:
            logger.warning("memory_propose validation failed: %s", exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        except Exception:
            logger.exception("memory_propose failed")
            return json.dumps({"error": _sanitize_unexpected_error(Exception())}, ensure_ascii=False)

    memory_propose.name = "memory_propose"  # type: ignore[attr-defined]
    return memory_propose


# --- Tool Implementations ---


@tool(args_schema=VaultReadFileInput)
def vault_read_file(relative_path: str) -> str:
    """Read content of a Markdown file inside the Obsidian Vault."""
    try:
        res = get_vault_file(relative_path)
        return json.dumps(res, ensure_ascii=False)
    except EXPECTED_TOOL_EXCEPTIONS as exc:
        logger.warning("vault_read_file failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool(args_schema=CalendarReadInput)
def calendar_read(
    start_date: str, end_date: str, calendar_name: Optional[str] = None
) -> str:
    """Fetch Apple Calendar and recurring config events within a start and end date range (YYYY-MM-DD). Use current date from system prompt for relative dates."""
    try:
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date)
        try:
            events = fetch_calendar_events(
                s_date, e_date, calendar_name=calendar_name
            )
        except Exception as exc:
            # Apple fetch may fail (e.g. not on macOS, ImportError); degrade to empty but still include recurring
            logger.warning("calendar_read Apple fetch failed, continuing with recurring only: %s", exc)
            events = []
        # Merge recurring config events (kind==event) for the same range
        try:
            from obsidian_ai_hub.planner.recurring import expand_recurring

            recurring_items = expand_recurring(s_date, e_date)
            recurring_events = _recurring_to_calendar_events(recurring_items)
            if recurring_events:
                # Append and sort by start time (all-day first by midnight)
                events = list(events) + recurring_events
                try:
                    events.sort(key=lambda e: e.get("start") or "")
                except Exception:
                    pass
        except Exception as rexc:
            logger.warning("calendar_read recurring merge failed: %s", rexc)

        return json.dumps({"events": events}, ensure_ascii=False)
    except EXPECTED_TOOL_EXCEPTIONS as exc:
        logger.warning("calendar_read failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool(args_schema=RemindersReadInput)
def reminders_read(start_date: str, end_date: str) -> str:
    """Fetch incomplete Apple Reminders and recurring config tasks due within a start and end date range (YYYY-MM-DD). Use current date from system prompt for relative dates."""
    try:
        s_date = date.fromisoformat(start_date)
        e_date = date.fromisoformat(end_date)
        try:
            reminders = fetch_incomplete_reminders(s_date, e_date)
        except Exception as exc:
            logger.warning("reminders_read Apple fetch failed, continuing with recurring only: %s", exc)
            reminders = []
        # Merge recurring config tasks (kind==task) for the same range
        try:
            from obsidian_ai_hub.planner.recurring import expand_recurring

            recurring_items = expand_recurring(s_date, e_date)
            recurring_reminders = _recurring_to_reminders(recurring_items)
            if recurring_reminders:
                reminders = list(reminders) + recurring_reminders
                try:
                    reminders.sort(key=lambda r: r.get("due") or "")
                except Exception:
                    pass
        except Exception as rexc:
            logger.warning("reminders_read recurring merge failed: %s", rexc)

        return json.dumps({"reminders": reminders}, ensure_ascii=False)
    except EXPECTED_TOOL_EXCEPTIONS as exc:
        logger.warning("reminders_read failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool(args_schema=CalendarCreateProposalInput)
def calendar_create_proposal(
    title: str,
    start_time: str,
    end_time: Optional[str] = None,
    location: Optional[str] = None,
    content: Optional[str] = None,
) -> str:
    """Create a proposal for adding a calendar event.

    IMPORTANT: This tool does NOT write directly to Apple Calendar.
    It registers a Human-In-The-Loop (HITL) approval run.
    """
    event = {
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
    }
    raw_content = content or title
    try:
        hitl_run_id = register_calendar_event_approval(raw_content, event)
        if not hitl_run_id:
            return json.dumps(
                {"error": "Failed to register HITL calendar proposal"},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "proposed",
                "hitl_run_id": hitl_run_id,
                "message": f"カレンダー登録の承認リクエスト（HITL）を作成しました (ID: {hitl_run_id})",
                "event": event,
            },
            ensure_ascii=False,
        )
    except EXPECTED_TOOL_EXCEPTIONS as exc:
        logger.warning("calendar_create_proposal failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


@tool(args_schema=ReminderCreateProposalInput)
def reminder_create_proposal(
    title: str, due_date: Optional[str] = None, content: Optional[str] = None
) -> str:
    """Create a proposal for adding a reminder.

    IMPORTANT: This tool does NOT write directly to Apple Reminders.
    It registers a Human-In-The-Loop (HITL) approval run.
    """
    reminder = {
        "title": title,
        "due_date": due_date,
    }
    raw_content = content or title
    try:
        hitl_run_id = register_reminder_approval(raw_content, reminder)
        if not hitl_run_id:
            return json.dumps(
                {"error": "Failed to register HITL reminder proposal"},
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "proposed",
                "hitl_run_id": hitl_run_id,
                "message": f"リマインダー登録の承認リクエスト（HITL）を作成しました (ID: {hitl_run_id})",
                "reminder": reminder,
            },
            ensure_ascii=False,
        )
    except EXPECTED_TOOL_EXCEPTIONS as exc:
        logger.warning("reminder_create_proposal failed: %s", exc)
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


# --- Tool Registry Definition ---

_BUILTIN_TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "web_search": {
        "tool_id": "web_search",
        "name": "Web検索",
        "description": "Tavilyを使用してWebを検索します。",
        "get_tool": lambda: web_search,
    },
    "web_extract": {
        "tool_id": "web_extract",
        "name": "Web本文抽出",
        "description": "指定URLの本文テキストを抽出します。",
        "get_tool": lambda: web_extract,
    },
    "vault_search": {
        "tool_id": "vault_search",
        "name": "Vault検索",
        "description": "Obsidian Vault内を検索します。",
        "get_tool": lambda: search_obsidian_vault,
    },
    "vault_read_file": {
        "tool_id": "vault_read_file",
        "name": "Vaultファイル読取",
        "description": "Obsidian Vault内のMarkdownファイルを読み込みます。",
        "get_tool": lambda: vault_read_file,
    },
    "calendar_read": {
        "tool_id": "calendar_read",
        "name": "カレンダー読取",
        "description": "Apple カレンダーと定期予定（config.yml）の予定を取得します。",
        "get_tool": lambda: calendar_read,
    },
    "reminders_read": {
        "tool_id": "reminders_read",
        "name": "リマインダー読取",
        "description": "Apple リマインダーと定期タスク（config.yml）の未完了タスクを取得します。",
        "get_tool": lambda: reminders_read,
    },
    "calendar_create_proposal": {
        "tool_id": "calendar_create_proposal",
        "name": "カレンダー作成提案 (HITL)",
        "description": "カレンダーへの予定追加をユーザーへ承認申請（HITL）します。",
        "get_tool": lambda: calendar_create_proposal,
    },
    "reminder_create_proposal": {
        "tool_id": "reminder_create_proposal",
        "name": "リマインダー作成提案 (HITL)",
        "description": "リマインダーへのタスク追加をユーザーへ承認申請（HITL）します。",
        "get_tool": lambda: reminder_create_proposal,
    },
    "memory_search": {
        "tool_id": "memory_search",
        "name": "長期記憶検索",
        "description": "承認済み長期記憶（approved）を検索します。ユーザーの嗜好や過去の事実が関係する質問では回答前に必ず呼び出し、結果の content を根拠として回答に反映してください。",
        "get_tool": lambda: _make_memory_search_tool(),
        "get_tool_with_context": lambda ctx: _make_memory_search_tool(ctx),
    },
    "memory_propose": {
        "tool_id": "memory_propose",
        "name": "長期記憶候補作成",
        "description": "ユーザーが嗜好・事実・方針を明示した内容を長期記憶候補（candidate）として保存します。推測で作成せず、明確な根拠がある場合のみ呼び出してください。保存後はメモリ画面で人間が承認します。",
        "get_tool": lambda: _make_memory_propose_tool(None),
        "get_tool_with_context": lambda ctx: _make_memory_propose_tool(ctx),
    },
}

_BUILTIN_TOOL_IDS = set(_BUILTIN_TOOL_DEFINITIONS.keys())

# The public catalog.  Built-ins are copied into this dict and then plugin
# tools (``custom:*``) are merged in place.  Mutated in place on reload so
# existing ``from ... import TOOL_DEFINITIONS`` references stay valid.
TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = dict(_BUILTIN_TOOL_DEFINITIONS)


def _normalize_plugin_tool_id(raw_id: str) -> str:
    """Ensure a plugin tool_id is ``custom:``-prefixed."""
    tid = (raw_id or "").strip()
    if not tid:
        return ""
    if tid.startswith(PLUGIN_TOOL_ID_PREFIX):
        return tid
    # Auto-prefix; sanitize by lowercasing + replacing invalid chars already
    # handled by the caller. The prefix guarantees built-ins can never be
    # shadowed.
    return f"{PLUGIN_TOOL_ID_PREFIX}{tid}"


def _validate_plugin_entry(tool_id: str, meta: Dict[str, Any]) -> Optional[str]:
    """Return an error string if *meta* is invalid, else ``None``."""
    if not tool_id or not _PLUGIN_TOOL_ID_RE_COMPILED.match(tool_id):
        return f"tool_id '{tool_id}' must match { _PLUGIN_TOOL_ID_RE }"
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        return f"tool '{tool_id}' missing non-empty 'name'"
    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        return f"tool '{tool_id}' missing non-empty 'description'"
    get_tool = meta.get("get_tool")
    if not callable(get_tool):
        return f"tool '{tool_id}' missing callable 'get_tool'"
    gctx = meta.get("get_tool_with_context")
    if gctx is not None and not callable(gctx):
        return f"tool '{tool_id}' has non-callable 'get_tool_with_context'"
    return None


def _load_plugins_into(target: Dict[str, Dict[str, Any]]) -> int:
    """Scan ``PLUGINS_TOOLS_DIR`` and merge plugin definitions into *target*.

    Each ``*.py`` file may expose ``register() -> dict`` or a module-level
    ``TOOL_DEFINITIONS`` dict.  Loaded ``tool_id`` values are normalized to
    the ``custom:`` namespace.  Built-in IDs win unconditionally; among
    plugins the first file (alphabetical) wins.

    One broken plugin file never prevents other plugins or the server from
    starting: the failure is logged with a full traceback and that file is
    skipped.  This is deliberate plugin isolation (``AGENTS.md``'s
    ``Do not mask unexpected failures`` applies to unexpected *application*
    failures, not to user-supplied extension files).
    """
    try:
        from obsidian_ai_hub.utils import config as _cfg

        plugins_dir = Path(_cfg.PLUGINS_TOOLS_DIR)
    except Exception as exc:
        logger.warning("Could not resolve PLUGINS_TOOLS_DIR, skipping plugin load: %s", exc)
        return 0

    if not plugins_dir.exists() or not plugins_dir.is_dir():
        return 0

    loaded = 0
    # Deterministic order: alphabetical by filename
    try:
        candidates = sorted(plugins_dir.glob("*.py"))
    except Exception as exc:
        logger.warning("Failed to list plugin directory %s: %s", plugins_dir, exc)
        return 0

    for file_path in candidates:
        stem = file_path.stem
        # Skip private / dunder files
        if stem.startswith("_") or stem.startswith("."):
            continue
        module_name = f"_oaih_plugin_{stem}"
        # Avoid stale module on reload
        if module_name in sys.modules:
            # Remove so the fresh file contents are re-executed.  A previous
            # broken import may have left a half-initialised entry.
            sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            logger.warning("Skipping plugin file with no import spec: %s", file_path)
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Failed to load plugin file %s (skipping)", file_path)
            # Ensure half-initialised module does not linger
            sys.modules.pop(module_name, None)
            continue
        # Keep the successfully loaded module cached so reload can find it.
        sys.modules[module_name] = module

        # Discover definitions
        raw_defs: Optional[Dict[str, Dict[str, Any]]] = None
        if hasattr(module, "register") and callable(getattr(module, "register")):
            try:
                result = module.register()  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Plugin %s register() raised (skipping)", file_path)
                continue
            if not isinstance(result, dict):
                logger.warning("Plugin %s register() must return dict, got %s (skipping)", file_path, type(result).__name__)
                continue
            raw_defs = result
        elif hasattr(module, "TOOL_DEFINITIONS"):
            td = getattr(module, "TOOL_DEFINITIONS")
            if not isinstance(td, dict):
                logger.warning("Plugin %s TOOL_DEFINITIONS must be dict, got %s (skipping)", file_path, type(td).__name__)
                continue
            raw_defs = td
        else:
            logger.warning(
                "Plugin %s exposes neither register() nor TOOL_DEFINITIONS (skipping). "
                "Define register() -> dict or TOOL_DEFINITIONS dict.",
                file_path,
            )
            continue

        for raw_key, meta in raw_defs.items():
            if not isinstance(meta, dict):
                logger.warning("Plugin %s entry '%s' must be dict, got %s (skipping entry)", file_path, raw_key, type(meta).__name__)
                continue
            # Prefer the entry's own tool_id, fall back to the dict key
            raw_tid = str(meta.get("tool_id") or raw_key or "").strip()
            norm_tid = _normalize_plugin_tool_id(raw_tid)
            if not norm_tid:
                logger.warning("Plugin %s entry '%s' has empty tool_id (skipping entry)", file_path, raw_key)
                continue
            # Reflect the normalized id back into the meta copy so resolve
            # sees the canonical key.
            normalized_meta: Dict[str, Any] = dict(meta)
            normalized_meta["tool_id"] = norm_tid
            # Validate shape
            err = _validate_plugin_entry(norm_tid, normalized_meta)
            if err:
                logger.warning("Plugin %s entry '%s' invalid: %s (skipping entry)", file_path, raw_key, err)
                continue
            # Collision policy: built-ins win; first plugin wins
            if norm_tid in target:
                if norm_tid in _BUILTIN_TOOL_IDS:
                    logger.warning(
                        "Plugin %s tool_id '%s' collides with built-in tool; skipping (built-in wins)",
                        file_path,
                        norm_tid,
                    )
                else:
                    logger.warning(
                        "Plugin %s tool_id '%s' collides with earlier plugin; skipping (first wins)",
                        file_path,
                        norm_tid,
                    )
                continue
            target[norm_tid] = normalized_meta
            loaded += 1
            logger.info("Registered plugin tool '%s' from %s", norm_tid, file_path.name)

    if loaded:
        logger.info("Loaded %d plugin tool(s) from %s", loaded, plugins_dir)
    return loaded


def reload_plugins() -> int:
    """Rebuild :data:`TOOL_DEFINITIONS` from built-ins plus current plugin files.

    Mutates the existing dict object in place so ``from ... import
    TOOL_DEFINITIONS`` references remain valid.  Returns the number of plugin
    tools loaded.  Intended for tests and manual refresh; the server loads
    plugins eagerly at import.
    """
    # Remove custom entries, keep built-ins
    for tid in list(TOOL_DEFINITIONS.keys()):
        if tid not in _BUILTIN_TOOL_IDS:
            TOOL_DEFINITIONS.pop(tid, None)
    # Also remove any stale ``_oaih_plugin_*`` modules so the next scan
    # re-executes the file.  Broken files that were skipped left no entry.
    for name in list(sys.modules.keys()):
        if name.startswith("_oaih_plugin_"):
            sys.modules.pop(name, None)
    # Ensure built-ins are present (in case a test did patch.dict(..., clear=True))
    for tid, meta in _BUILTIN_TOOL_DEFINITIONS.items():
        TOOL_DEFINITIONS.setdefault(tid, meta)
    return _load_plugins_into(TOOL_DEFINITIONS)


# Eager load at import.  An absent directory is a no-op; a broken file is
# logged and skipped without aborting import.
try:
    _load_plugins_into(TOOL_DEFINITIONS)
except Exception:
    # Defensive: a catastrophic loader bug must never prevent the registry
    # from being importable (built-ins remain usable).  The traceback is
    # preserved for diagnosis.
    logger.exception("Unexpected error during eager plugin load (continuing with built-ins only)")


def list_available_tools() -> List[Dict[str, Any]]:
    """Return catalog metadata for all registered tools."""
    catalog = []
    for tool_id, meta in TOOL_DEFINITIONS.items():
        catalog.append(
            {
                "tool_id": tool_id,
                "name": meta["name"],
                "description": meta["description"],
            }
        )
    return catalog


def resolve_tools(tool_ids: Sequence[str]) -> List[BaseTool]:
    """Validate tool_ids, deduplicate, and return active LangChain BaseTool objects."""
    tools: List[BaseTool] = []
    seen = set()
    for tid in tool_ids:
        if not tid or tid in seen:
            continue
        seen.add(tid)
        meta = TOOL_DEFINITIONS.get(tid)
        if not meta:
            logger.warning("Requested tool_id '%s' is not in server registry; skipping", tid)
            continue
        tool_obj = meta["get_tool"]()
        tools.append(tool_obj)
    return tools


def resolve_tools_with_context(
    tool_ids: Sequence[str], trusted_ctx: Dict[str, Any]
) -> List[BaseTool]:
    """Like resolve_tools but binds trusted execution context to context-aware tools.

    Tools that define ``get_tool_with_context`` receive the trusted_ctx
    (agent_id, session_id, run_id, etc.) and can embed it in their closure
    without exposing it to the LLM.

    The trusted_ctx snapshot is shallow-copied per tool so the binding cannot
    be mutated after this function returns (callers may reuse the dict across
    runs or async tasks).
    """
    tools: List[BaseTool] = []
    seen = set()
    for tid in tool_ids:
        if not tid or tid in seen:
            continue
        seen.add(tid)
        meta = TOOL_DEFINITIONS.get(tid)
        if not meta:
            logger.warning("Requested tool_id '%s' is not in server registry; skipping", tid)
            continue
        if "get_tool_with_context" in meta:
            # Copy the snapshot so the tool closure cannot observe later
            # mutations to the caller's dict.
            ctx_snapshot = dict(trusted_ctx) if trusted_ctx is not None else {}
            try:
                tool_obj = meta["get_tool_with_context"](ctx_snapshot)  # type: ignore[operator]
            except Exception as exc:
                # Re-raise so mis-bound trusted_ctx / broken factories are
                # visible. The runtime caller may choose to fall back to
                # resolve_tools if it wants degraded behavior.
                logger.exception("Failed to create contextual tool %s: %s", tid, exc)
                raise
        else:
            tool_obj = meta["get_tool"]()
        tools.append(tool_obj)
    return tools

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

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

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

EXPECTED_TOOL_EXCEPTIONS = (
    FileNotFoundError,
    ValueError,
    KeyError,
    TypeError,
    PermissionError,
)

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

TOOL_DEFINITIONS: Dict[str, Dict[str, Any]] = {
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
}


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

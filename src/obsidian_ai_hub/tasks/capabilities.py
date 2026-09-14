"""Code-defined Task Agent capability catalog.

This module is the source of truth for adapter keys, input validation anchors,
labels, and descriptions. The ``task_agent_capabilities`` table is the source
of truth only for ``enabled`` and ``approval_policy``; the v44 migration seeds
this catalog idempotently without overwriting those two columns.

Registry-backed entries resolve ``registry_tool_id`` against the existing
Agent tool registry in Phase 3 (``tasks/adapters/registry_tools.py``). The
allowlist is fixed here: ``run_shell``, Skills, custom plugins, external-write
proposals, and the calendar/reminder create-proposal tools are excluded.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityDefinition:
    """A single code-defined capability."""

    key: str
    adapter_kind: str  # "registry_tool" | "memory" | "agent" | "coding"
    label: str
    description: str
    default_approval_policy: str  # "auto" | "plan_required"
    registry_tool_id: str | None = None


CAPABILITY_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    # Read/search-only existing Registry tools (auto).
    CapabilityDefinition(
        key="web_search",
        adapter_kind="registry_tool",
        label="Web検索",
        description="Webを検索する。",
        default_approval_policy="auto",
        registry_tool_id="web_search",
    ),
    CapabilityDefinition(
        key="web_extract",
        adapter_kind="registry_tool",
        label="Web本文抽出",
        description="指定URLの本文テキストを抽出する。",
        default_approval_policy="auto",
        registry_tool_id="web_extract",
    ),
    CapabilityDefinition(
        key="vault_search",
        adapter_kind="registry_tool",
        label="Vault検索",
        description="Obsidian Vault内を検索する。",
        default_approval_policy="auto",
        registry_tool_id="vault_search",
    ),
    CapabilityDefinition(
        key="vault_read_file",
        adapter_kind="registry_tool",
        label="Vaultファイル読取",
        description="Obsidian Vault内のMarkdownファイルを読み込む。",
        default_approval_policy="auto",
        registry_tool_id="vault_read_file",
    ),
    CapabilityDefinition(
        key="calendar_read",
        adapter_kind="registry_tool",
        label="カレンダー読取",
        description="カレンダーの予定を取得する。",
        default_approval_policy="auto",
        registry_tool_id="calendar_read",
    ),
    CapabilityDefinition(
        key="reminders_read",
        adapter_kind="registry_tool",
        label="リマインダー読取",
        description="リマインダーの未完了タスクを取得する。",
        default_approval_policy="auto",
        registry_tool_id="reminders_read",
    ),
    CapabilityDefinition(
        key="memory_search",
        adapter_kind="registry_tool",
        label="長期記憶検索",
        description="承認済み長期記憶を検索する。",
        default_approval_policy="auto",
        registry_tool_id="memory_search",
    ),
    CapabilityDefinition(
        key="people_search",
        adapter_kind="registry_tool",
        label="人物検索",
        description="確定済み人物を検索する。",
        default_approval_policy="auto",
        registry_tool_id="people_search",
    ),
    CapabilityDefinition(
        key="people_get",
        adapter_kind="registry_tool",
        label="人物詳細取得",
        description="人物IDから詳細を取得する。",
        default_approval_policy="auto",
        registry_tool_id="people_get",
    ),
    CapabilityDefinition(
        key="project_search",
        adapter_kind="registry_tool",
        label="プロジェクト検索",
        description="確定済みプロジェクトを検索する。",
        default_approval_policy="auto",
        registry_tool_id="project_search",
    ),
    CapabilityDefinition(
        key="project_get",
        adapter_kind="registry_tool",
        label="プロジェクト詳細取得",
        description="プロジェクトIDから詳細を取得する。",
        default_approval_policy="auto",
        registry_tool_id="project_get",
    ),
    # Write/delegate capabilities (plan_required: whole-plan bulk approval).
    CapabilityDefinition(
        key="memory_propose",
        adapter_kind="memory",
        label="長期記憶候補作成",
        description="長期記憶候補を作成する。",
        default_approval_policy="plan_required",
        registry_tool_id="memory_propose",
    ),
    CapabilityDefinition(
        key="specialist_agent",
        adapter_kind="agent",
        label="専門Agent委譲",
        description="登録済みAI Agentを指定して一回限りの子runを作る。",
        default_approval_policy="plan_required",
    ),
    CapabilityDefinition(
        key="coding_cli",
        adapter_kind="coding",
        label="Coding CLI実行",
        description="登録済みProjectのGit rootで新規Coding session/runを作る。",
        default_approval_policy="plan_required",
    ),
)

CAPABILITY_KEYS: frozenset[str] = frozenset(d.key for d in CAPABILITY_DEFINITIONS)

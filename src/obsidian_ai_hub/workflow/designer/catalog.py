"""Catalog search and detail retrieval for Workflow Designer.

Privacy Boundary Rules:
- Capabilities: returns metadata and schemas (ui_input_schema, ui_target_schema, ui_output_schema).
- Agents: returns agent_id, name, description, allowed_tools. NO system_prompt or system_prompt_template.
- Projects: returns project_id, display_name. NO working_path, tasks, or internal details.
- People: returns person_id, display_name. NO person properties, relations, notes, or memories.
- Vault: returns relative note paths only. NO vault note contents.
- Search result limit: maximum 10 items per search call.
"""

from __future__ import annotations

import logging
import os
from contextlib import closing
from pathlib import Path
from typing import Any, Optional

from obsidian_ai_hub.agents import store as agent_store
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.tasks.capability_schemas import (
    mixed_output_field_contracts,
    ui_input_schema,
    ui_output_schema,
    ui_target_schema,
)
from obsidian_ai_hub.utils.config import VAULT_PATH
from obsidian_ai_hub.workflow.capabilities import (
    WORKFLOW_ONLY_INPUT_SCHEMA,
    WORKFLOW_ONLY_KEYS,
    WORKFLOW_ONLY_METADATA,
    WORKFLOW_ONLY_OUTPUT_SCHEMA,
    is_strict_allowed,
    output_contract_class,
    workflow_capability_keys,
    workflow_output_schema,
)

CATALOG_SEARCH_LIMIT = 10

logger = logging.getLogger(__name__)


def _capability_enabled_map() -> dict[str, bool]:
    """Return capability_key -> enabled from the DB policy table.

    On lookup failure returns an empty map (callers treat unknown keys as
    disabled) and logs a warning so a DB outage stays visible instead of
    silently flipping every capability to disabled.
    """
    try:
        return {
            str(c["capability_key"]): bool(c.get("enabled"))
            for c in task_store.list_capabilities()
        }
    except Exception as exc:
        logger.warning("Capability enablement lookup failed: %s", exc)
        return {}


def catalog_search(query: str = "", target: str = "capability") -> list[dict[str, Any]]:
    """Search the catalog for available resources.

    Returns a maximum of 10 items with minimal display information.
    """
    query_clean = (query or "").strip().lower()
    target_clean = (target or "capability").strip().lower()

    if target_clean == "capability":
        definitions = {c.key: c for c in get_capability_definitions()}
        enabled_map = _capability_enabled_map()
        results: list[dict[str, Any]] = []
        for key in sorted(workflow_capability_keys()):
            cap = definitions.get(key)
            if cap is not None:
                label = cap.label or key
                desc = cap.description or ""
                read_only = cap.read_only
            else:
                label, desc = WORKFLOW_ONLY_METADATA.get(key, (key, ""))
                read_only = False
            if not query_clean or query_clean in key.lower() or query_clean in label.lower() or query_clean in desc.lower():
                results.append({
                    "target": "capability",
                    "capability_key": key,
                    "label": label,
                    "description": desc,
                    "enabled": True if key in WORKFLOW_ONLY_KEYS else enabled_map.get(key, False),
                    "read_only": read_only,
                    "output_contract_class": output_contract_class(key),
                    "output_field_contracts": mixed_output_field_contracts(key),
                    "strict_allowed": is_strict_allowed(key),
                })
                if len(results) >= CATALOG_SEARCH_LIMIT:
                    break
        return results

    if target_clean == "agent":
        all_agents = agent_store.list_agents()
        results = []
        for ag in all_agents:
            agent_id = str(ag.get("agent_id") or "")
            name = str(ag.get("name") or "")
            desc = str(ag.get("description") or "")
            tools = ag.get("tool_ids") or []
            if not query_clean or query_clean in agent_id.lower() or query_clean in name.lower() or query_clean in desc.lower():
                results.append({
                    "target": "agent",
                    "agent_id": agent_id,
                    "name": name,
                    "description": desc,
                    "allowed_tools": list(tools),
                })
                if len(results) >= CATALOG_SEARCH_LIMIT:
                    break
        return results

    if target_clean == "project":
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                """
                SELECT project_id, display_name
                FROM projects
                WHERE ? = '' OR LOWER(display_name) LIKE ? OR LOWER(project_id) LIKE ?
                ORDER BY display_name ASC
                LIMIT ?
                """,
                (
                    query_clean,
                    f"%{query_clean}%",
                    f"%{query_clean}%",
                    CATALOG_SEARCH_LIMIT,
                ),
            ).fetchall()
            return [
                {
                    "target": "project",
                    "project_id": str(r["project_id"]),
                    "display_name": str(r["display_name"]),
                }
                for r in rows
            ]

    if target_clean == "person":
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                """
                SELECT person_id, display_name
                FROM people
                WHERE ? = '' OR LOWER(display_name) LIKE ? OR LOWER(person_id) LIKE ?
                ORDER BY display_name ASC
                LIMIT ?
                """,
                (
                    query_clean,
                    f"%{query_clean}%",
                    f"%{query_clean}%",
                    CATALOG_SEARCH_LIMIT,
                ),
            ).fetchall()
            return [
                {
                    "target": "person",
                    "person_id": str(r["person_id"]),
                    "display_name": str(r["display_name"]),
                }
                for r in rows
            ]

    if target_clean == "vault":
        vault_root = Path(VAULT_PATH)
        matches: list[dict[str, Any]] = []
        if vault_root.exists():
            for root, dirs, files in os.walk(vault_root):
                dirs.sort()
                for f in sorted(files):
                    if not f.endswith(".md"):
                        continue
                    full_p = Path(root) / f
                    try:
                        rel_p = str(full_p.relative_to(vault_root))
                    except ValueError:
                        continue
                    if not query_clean or query_clean in rel_p.lower():
                        matches.append({
                            "target": "vault",
                            "relative_path": rel_p,
                        })
                        if len(matches) >= CATALOG_SEARCH_LIMIT:
                            break
                if len(matches) >= CATALOG_SEARCH_LIMIT:
                    break
        return matches

    return []


def catalog_get_details(target: str, item_id: str) -> dict[str, Any]:
    """Get detailed schema or metadata for a single item.

    Does NOT expose private data (such as agent prompts, vault text, project details, or person properties).
    """
    target_clean = (target or "").strip().lower()
    item_clean = (item_id or "").strip()

    if target_clean == "capability":
        definitions = {c.key: c for c in get_capability_definitions()}
        cap = definitions.get(item_clean)
        if cap is None and item_clean not in WORKFLOW_ONLY_KEYS:
            return {"ok": False, "code": "capability_not_found", "message": f"Capability '{item_clean}' が見つかりません"}
        if cap is not None:
            label = cap.label or cap.key
            description = cap.description or ""
            read_only = cap.read_only
            input_schema: Any = ui_input_schema(cap.key)
            target_schema: Any = ui_target_schema(cap.key)
            output_schema: Any = ui_output_schema(cap.key)
        else:
            label, description = WORKFLOW_ONLY_METADATA.get(item_clean, (item_clean, ""))
            read_only = False
            input_schema = WORKFLOW_ONLY_INPUT_SCHEMA.get(item_clean)
            target_schema = None
            output_schema = WORKFLOW_ONLY_OUTPUT_SCHEMA.get(item_clean)
        enabled_map = _capability_enabled_map()
        return {
            "ok": True,
            "target": "capability",
            "capability_key": item_clean,
            "label": label,
            "description": description,
            "enabled": True if item_clean in WORKFLOW_ONLY_KEYS else enabled_map.get(item_clean, False),
            "read_only": read_only,
            "output_contract_class": output_contract_class(item_clean),
            "output_field_contracts": mixed_output_field_contracts(item_clean),
            "strict_allowed": is_strict_allowed(item_clean),
            "ui_input_schema": input_schema,
            "ui_target_schema": target_schema,
            "ui_output_schema": output_schema,
            "workflow_output_schema": workflow_output_schema(item_clean),
        }

    if target_clean == "agent":
        ag = agent_store.get_agent(item_clean)
        if not ag:
            return {"ok": False, "code": "agent_not_found", "message": f"Agent '{item_clean}' が見つかりません"}
        return {
            "ok": True,
            "target": "agent",
            "agent_id": str(ag.get("agent_id")),
            "name": str(ag.get("name")),
            "description": str(ag.get("description") or ""),
            "allowed_tools": list(ag.get("tool_ids") or []),
        }

    if target_clean == "project":
        with closing(get_db_connection()) as conn:
            r = conn.execute(
                "SELECT project_id, display_name FROM projects WHERE project_id = ?",
                (item_clean,),
            ).fetchone()
            if not r:
                return {"ok": False, "code": "project_not_found", "message": f"Project '{item_clean}' が見つかりません"}
            return {
                "ok": True,
                "target": "project",
                "project_id": str(r["project_id"]),
                "display_name": str(r["display_name"]),
            }

    if target_clean == "person":
        with closing(get_db_connection()) as conn:
            r = conn.execute(
                "SELECT person_id, display_name FROM people WHERE person_id = ?",
                (item_clean,),
            ).fetchone()
            if not r:
                return {"ok": False, "code": "person_not_found", "message": f"Person '{item_clean}' が見つかりません"}
            return {
                "ok": True,
                "target": "person",
                "person_id": str(r["person_id"]),
                "display_name": str(r["display_name"]),
            }

    if target_clean == "vault":
        vault_root = Path(VAULT_PATH).resolve()
        try:
            full_path = (vault_root / item_clean).resolve()
            rel_path = str(full_path.relative_to(vault_root))
        except (ValueError, RuntimeError):
            return {"ok": False, "code": "invalid_vault_path", "message": f"不正な Vault パスです: {item_clean}"}

        if not full_path.exists() or not full_path.is_file():
            return {"ok": False, "code": "vault_path_not_found", "message": f"Vault パス '{item_clean}' が見つかりません"}

        return {
            "ok": True,
            "target": "vault",
            "relative_path": rel_path,
        }

    return {"ok": False, "code": "invalid_target", "message": f"未対応のターゲットです: {target}"}

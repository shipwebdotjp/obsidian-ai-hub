from __future__ import annotations

import json
import logging
from pathlib import Path

from obsidian_ai_hub.utils import config, prompt

from obsidian_ai_hub.memory.context import get_currently_valid_approved_memories
from obsidian_ai_hub.memory.models import (
    _vault_relative_path,
    get_approved_memories_path,
    get_current_timestamp,
)
from obsidian_ai_hub.memory.store import load_all_memories

logger = logging.getLogger(__name__)


def project_approved_memories():
    approved_md_file = get_approved_memories_path()
    approved_md_file.parent.mkdir(parents=True, exist_ok=True)

    memories = load_all_memories()
    active_approved = [m for m in memories if m.get("status") == "approved"]

    # Keep a fixed order of kinds
    kinds_order = [
        "preference",
        "decision_policy",
        "fact",
        "commitment",
        "pattern",
        "episode",
    ]
    grouped_memories = {k: [] for k in kinds_order}
    for m in active_approved:
        kind = m.get("kind", "preference")
        if kind not in grouped_memories:
            grouped_memories[kind] = []
        grouped_memories[kind].append(m)

    lines = [
        "# Approved Memories",
        "",
        "> Generated from the SQLite memory database. Do not edit manually.",
        "",
    ]

    for kind in kinds_order:
        m_list = grouped_memories[kind]
        if not m_list:
            continue
        lines.append(f"## {kind}")
        lines.append("")
        for m in m_list:
            lines.append(f"### {m['memory_id']}")
            lines.append("")
            lines.append(m.get("content", ""))
            lines.append("")
            lines.append(f"- Key: `{m.get('memory_key', '')}`")
            lines.append(f"- Stability: `{m.get('stability', 'stable')}`")
            evidence_lines = []
            for ev in m.get("evidence") or []:
                path = ev.get("path", "")
                if path.endswith(".md"):
                    path = path[:-3]
                quote = ev.get("quote", "")
                evidence_lines.append(f"[[{path}]] — 「{quote}」")
            if evidence_lines:
                lines.append(f"- Evidence: {', '.join(evidence_lines)}")
            lines.append("")

    with open(approved_md_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).strip() + "\n")


EXPECTED_FILES = {
    "AI_README.md": "AI全体プロフィールと横断的指針 (AI Profile & Guidelines)",
    "values.md": "明示された価値観・優先順位 (Values)",
    "response_style.md": "応答・対話スタイルの好み (Response Style)",
    "decision_policy.md": "判断方針・優先順位 (Decision Policy)",
    "risk_tolerance.md": "リスク許容度・慎重さの方針 (Risk Tolerance)",
    "memory_rules.md": "明示された記憶管理ルール (Memory Rules)",
    "current_projects.md": "現在進行中のプロジェクト・コミットメント (Current Projects)",
}


def render_copilot_profile() -> list[str]:
    """
    Summarize approved and valid memories and render the copilot profile markdown files.
    Returns:
        List of updated relative file paths.
    """
    logger.info("Starting copilot profile rendering")

    # Get active/valid approved memories
    active_approved, _ = get_currently_valid_approved_memories()

    # Build file mapping and absolute paths
    copilot_dir = Path(config.VAULT_PATH) / "copilot"
    core_dir = copilot_dir / "core"

    copilot_dir.mkdir(parents=True, exist_ok=True)
    core_dir.mkdir(parents=True, exist_ok=True)

    file_paths = {}
    for filename in EXPECTED_FILES:
        if filename == "AI_README.md":
            file_paths[filename] = copilot_dir / filename
        else:
            file_paths[filename] = core_dir / filename

    timestamp = get_current_timestamp()

    # 7 expected keys
    expected_keys = set(EXPECTED_FILES.keys())

    contents = {}
    if not active_approved:
        logger.info(
            "No active approved memories found. Generating fallback notice for all files."
        )
        for filename in expected_keys:
            contents[filename] = "現時点で承認済みメモリなし"
    else:
        # Prepare filtered memories for LLM input
        filtered_memories = []
        for m in active_approved:
            filtered_m = {
                "kind": m.get("kind"),
                "memory_key": m.get("memory_key"),
                "content": m.get("content"),
                "topics": m.get("topics"),
                "tags": m.get("tags"),
                "valid_from": m.get("valid_from"),
                "valid_until": m.get("valid_until"),
                "stability": m.get("stability"),
                "sensitivity": m.get("sensitivity"),
                "extraction_confidence": m.get("extraction_confidence"),
            }
            filtered_memories.append(filtered_m)

        json_memories = json.dumps(filtered_memories, ensure_ascii=False, indent=2)

        # Render prompt
        rendered_prompt = prompt.render_prompt(
            config.MEMORY_RENDERER_PROMPT_PATH, {"memories": json_memories}
        )

        # Call LLM
        from obsidian_ai_hub import memory as _memory_facade

        response = _memory_facade.llm_client.generate_llm_response(
            provider=config.MEMORY_RENDERER_PROVIDER,
            model=config.MEMORY_RENDERER_MODEL,
            prompt=rendered_prompt,
            max_tokens=32000,
            temperature=0.2,
        ).strip()

        # Clean response
        if response.startswith("```"):
            lines = response.splitlines()
            if len(lines) >= 2:
                if lines[0].startswith("```json") or lines[0].startswith("```"):
                    response = "\n".join(lines[1:-1]).strip()

        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse LLM response as JSON: {e}. Response was: {response}"
            )
            raise ValueError(f"LLM response is not a valid JSON string: {e}")

        if not isinstance(data, dict):
            logger.error(f"LLM response is not a JSON object: {data}")
            raise ValueError("LLM output is not a JSON object/dictionary")

        # Validation checks
        actual_keys = set(data.keys())
        if actual_keys != expected_keys:
            logger.error(
                f"JSON key mismatch. Expected keys: {expected_keys}. Got: {actual_keys}"
            )
            raise ValueError(f"JSON key mismatch. Expected exactly: {expected_keys}")

        for key, val in data.items():
            if not isinstance(val, str) or not val.strip():
                logger.error(f"Key {key} has an invalid or empty value: {val!r}")
                raise ValueError(f"Key '{key}' must have a non-empty string value")
            contents[key] = val.strip()

    # Write files if validation succeeds
    updated_paths = []
    for filename, body in contents.items():
        title = EXPECTED_FILES[filename]
        dest_path = file_paths[filename]

        # Generate full markdown
        markdown_content = f"""---
type: copilot-profile
generated_at: {timestamp}
---

# {title}

> [!NOTE]
> このファイルは承認済み長期記憶から自動生成されました。手書きでの変更は保持されません。

{body}
"""
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        # relative to VAULT_PATH
        relative_p = _vault_relative_path(dest_path)
        updated_paths.append(relative_p)

    logger.info("Copilot profile rendering completed successfully.")
    return sorted(updated_paths)

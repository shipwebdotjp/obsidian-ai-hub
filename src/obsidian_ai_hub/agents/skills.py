"""Agent Skills capability: discovery, indexing, and safe skill tools."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from obsidian_ai_hub.utils import config

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 20_000
MAX_RESOURCE_CHARS = 20_000
MAX_OUTPUT_CHARS = 20_000
MAX_SCRIPT_ARGS = 20
SCRIPT_TIMEOUT_SECONDS = 60


class SkillInfo:
    """Metadata and file location of an indexed skill."""

    def __init__(self, name: str, description: str, skill_dir: Path, skill_md_path: Path):
        self.name = name
        self.description = description
        self.skill_dir = skill_dir
        self.skill_md_path = skill_md_path


class SkillIndex:
    """Frozen index of discovered skills from primary and secondary roots."""

    def __init__(self, skills: Dict[str, SkillInfo]):
        self.skills: Dict[str, SkillInfo] = skills

    def get_catalog_summary(self) -> List[Dict[str, str]]:
        """Return name and short description for prompt catalog."""
        return [
            {"name": info.name, "description": info.description}
            for info in sorted(self.skills.values(), key=lambda s: s.name)
        ]


def _is_safe_symlink_or_path(target_path: Path, root_dir: Path) -> bool:
    """Ensure target_path (and any symlink target) is strictly inside root_dir."""
    try:
        resolved_root = root_dir.resolve(strict=True)
        resolved_target = target_path.resolve(strict=True)
        resolved_target.relative_to(resolved_root)
        return True
    except (ValueError, FileNotFoundError, OSError):
        return False


def _parse_skill_md(skill_md_path: Path) -> Optional[Tuple[str, str, str]]:
    """Parse SKILL.md frontmatter for name and description.

    Returns (name, description, body) or None if invalid.
    """
    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to read %s: %s", skill_md_path, exc)
        return None

    if not content.startswith("---"):
        logger.warning("SKILL.md at %s missing leading frontmatter '---'", skill_md_path)
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        logger.warning("SKILL.md at %s has unclosed frontmatter", skill_md_path)
        return None

    raw_yaml = parts[1]
    body = parts[2].strip()

    try:
        meta = yaml.safe_load(raw_yaml)
    except Exception as exc:
        logger.warning("SKILL.md at %s has invalid YAML frontmatter: %s", skill_md_path, exc)
        return None

    if not isinstance(meta, dict):
        logger.warning("SKILL.md at %s frontmatter is not a dict", skill_md_path)
        return None

    name = meta.get("name")
    description = meta.get("description")

    if not isinstance(name, str) or not name.strip():
        logger.warning("SKILL.md at %s has missing or invalid 'name'", skill_md_path)
        return None

    if not isinstance(description, str) or not description.strip():
        logger.warning("SKILL.md at %s has missing or invalid 'description'", skill_md_path)
        return None

    return name.strip(), description.strip(), body


def discover_skills(
    primary_root: Optional[Path] = None,
    secondary_root: Optional[Path] = None,
) -> SkillIndex:
    """Discover and index Skills from primary and secondary roots.

    Secondary-root same-name Skill takes precedence over primary.
    Only Skills with valid frontmatter name and description are indexed.
    Invalid frontmatter, duplicates within root, and symlinks escaping root are excluded.
    """
    p_root = primary_root or getattr(config, "AGENT_SKILLS_PRIMARY_ROOT", Path("~/.agents/skills").expanduser())
    s_root = secondary_root or getattr(config, "AGENT_SKILLS_ROOT", Path("~/.config/obsidian-ai-hub/skills").expanduser())

    skills: Dict[str, SkillInfo] = {}

    def _scan_root(root: Path, is_secondary: bool) -> None:
        if not root.exists() or not root.is_dir():
            return

        try:
            entries = sorted(root.iterdir())
        except Exception as exc:
            logger.warning("Failed to list skills root %s: %s", root, exc)
            return

        seen_names_in_root: set[str] = set()

        for entry in entries:
            if not entry.is_dir():
                continue

            if not _is_safe_symlink_or_path(entry, root):
                logger.warning("Skill dir %s escapes root %s (symlink or traversal); skipping", entry, root)
                continue

            skill_md = entry / "SKILL.md"
            if not skill_md.exists() or not skill_md.is_file():
                continue

            if not _is_safe_symlink_or_path(skill_md, root):
                logger.warning("SKILL.md at %s escapes root %s; skipping", skill_md, root)
                continue

            parsed = _parse_skill_md(skill_md)
            if parsed is None:
                continue

            name, description, _ = parsed

            if name in seen_names_in_root:
                logger.warning("Duplicate skill name '%s' in same root %s; skipping entry %s", name, root, entry)
                continue

            seen_names_in_root.add(name)

            if not is_secondary and name in skills:
                # Primary root skill loses if secondary root already provided same name
                continue

            skills[name] = SkillInfo(
                name=name,
                description=description,
                skill_dir=entry,
                skill_md_path=skill_md,
            )

    # Scan primary first, then secondary (secondary overwrites primary if same name)
    _scan_root(p_root, is_secondary=False)
    _scan_root(s_root, is_secondary=True)

    return SkillIndex(skills)


def _truncate_text(text: str, limit: int = 20_000) -> Tuple[str, bool]:
    """Truncate text to limit characters. Returns (truncated_text, was_truncated)."""
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n…(truncated)", True


# --- Input Schemas ---


class LoadSkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Skill name to load.")


class ReadSkillResourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Skill name.")
    relative_path: str = Field(description="Path relative to skill directory (excluding SKILL.md and scripts/).")


class RunSkillScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Skill name.")
    relative_path: str = Field(description="Script path relative to scripts/ directory under the skill.")
    args: List[str] = Field(default_factory=list, description="Array of string arguments (max 20).")


# --- Tool Implementations ---


def _load_skill_impl(name: str, index: SkillIndex) -> str:
    info = index.skills.get(name)
    if not info:
        return json.dumps({"error": f"Skill '{name}' not found."}, ensure_ascii=False)

    parsed = _parse_skill_md(info.skill_md_path)
    if not parsed:
        return json.dumps({"error": f"Failed to parse SKILL.md for skill '{name}'."}, ensure_ascii=False)

    _, _, body = parsed
    truncated_body, _ = _truncate_text(body, MAX_BODY_CHARS)
    return truncated_body


def _read_skill_resource_impl(name: str, relative_path: str, index: SkillIndex) -> str:
    info = index.skills.get(name)
    if not info:
        return json.dumps({"error": f"Skill '{name}' not found."}, ensure_ascii=False)

    rel_p = Path(relative_path.strip())

    # Reject path traversal or absolute paths
    if rel_p.is_absolute() or ".." in rel_p.parts:
        return json.dumps({"error": "Path traversal or absolute path rejected."}, ensure_ascii=False)

    # Reject reading SKILL.md or anything under scripts/
    norm_parts = [p.lower() for p in rel_p.parts]
    if norm_parts and norm_parts[0] == "skill.md":
        return json.dumps({"error": "Reading SKILL.md via read_skill_resource is not allowed. Use load_skill instead."}, ensure_ascii=False)
    if norm_parts and norm_parts[0] == "scripts":
        return json.dumps({"error": "Reading files under scripts/ is not allowed."}, ensure_ascii=False)

    target = info.skill_dir / rel_p

    # Check containment within skill directory
    if not _is_safe_symlink_or_path(target, info.skill_dir):
        return json.dumps({"error": "Resource path escapes skill directory."}, ensure_ascii=False)

    if not target.exists() or not target.is_file():
        return json.dumps({"error": f"Resource file '{relative_path}' not found under skill '{name}'."}, ensure_ascii=False)

    try:
        content_bytes = target.read_bytes()
        # Check for UTF-8 decodability and binary/NUL bytes
        if b"\x00" in content_bytes:
            return json.dumps({"error": "Binary files are not supported."}, ensure_ascii=False)
        content_str = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return json.dumps({"error": "Resource file is not valid UTF-8 text."}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"Failed to read resource file: {exc}"}, ensure_ascii=False)

    truncated_str, _ = _truncate_text(content_str, MAX_RESOURCE_CHARS)
    return truncated_str


def _run_skill_script_impl(
    name: str,
    relative_path: str,
    args: List[str],
    index: SkillIndex,
) -> str:
    info = index.skills.get(name)
    if not info:
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Skill '{name}' not found.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    # Validate args
    if not isinstance(args, list):
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Arguments must be a string array.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    if len(args) > MAX_SCRIPT_ARGS:
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Maximum of {MAX_SCRIPT_ARGS} arguments allowed.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    for a in args:
        if not isinstance(a, str):
            return json.dumps(
                {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "All script arguments must be strings.",
                    "truncated": False,
                    "timeout": False,
                },
                ensure_ascii=False,
            )

    rel_p = Path(relative_path.strip())

    # Reject path traversal or absolute paths
    if rel_p.is_absolute() or ".." in rel_p.parts:
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Path traversal or absolute path rejected.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    scripts_dir = info.skill_dir / "scripts"
    target = scripts_dir / rel_p

    if not _is_safe_symlink_or_path(target, scripts_dir):
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "Script path escapes scripts/ directory.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    if not target.exists() or not target.is_file():
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Script '{relative_path}' not found under scripts/ for skill '{name}'.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    # Reject non-executable files
    if not os.access(target, os.X_OK):
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Script '{relative_path}' is not executable.",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    # Check for shebang
    try:
        with open(target, "rb") as f:
            first_bytes = f.read(2)
            if first_bytes != b"#!":
                return json.dumps(
                    {
                        "success": False,
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": f"Script '{relative_path}' does not have a valid shebang (#!).",
                        "truncated": False,
                        "timeout": False,
                    },
                    ensure_ascii=False,
                )
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Failed to inspect script shebang: {exc}",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    # Execute script without shell
    # cwd = skill directory, inherit process environment
    cmd = [str(target)] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=info.skill_dir,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=SCRIPT_TIMEOUT_SECONDS,
        )
        stdout_raw = proc.stdout or ""
        stderr_raw = proc.stderr or ""
        exit_code = proc.returncode
        is_timeout = False
    except subprocess.TimeoutExpired as texc:
        stdout_raw = texc.stdout if isinstance(texc.stdout, str) else (texc.stdout.decode("utf-8", errors="replace") if texc.stdout else "")
        stderr_raw = texc.stderr if isinstance(texc.stderr, str) else (texc.stderr.decode("utf-8", errors="replace") if texc.stderr else "")
        exit_code = -1
        is_timeout = True
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Script execution failed: {exc}",
                "truncated": False,
                "timeout": False,
            },
            ensure_ascii=False,
        )

    stdout_trunc, out_t = _truncate_text(stdout_raw, MAX_OUTPUT_CHARS)
    stderr_trunc, err_t = _truncate_text(stderr_raw, MAX_OUTPUT_CHARS)
    was_truncated = out_t or err_t

    success = (exit_code == 0) and not is_timeout

    res = {
        "success": success,
        "exit_code": exit_code,
        "stdout": stdout_trunc,
        "stderr": stderr_trunc,
        "truncated": was_truncated,
        "timeout": is_timeout,
    }
    return json.dumps(res, ensure_ascii=False)


def create_skill_tools(index: Optional[SkillIndex] = None) -> List[BaseTool]:
    """Create the 3 LangChain skill tools bound to a frozen SkillIndex."""
    frozen_index = index if index is not None else discover_skills()

    @tool(args_schema=LoadSkillInput)
    def load_skill(name: str) -> str:
        """Load and return SKILL.md body for a skill by name."""
        return _load_skill_impl(name, frozen_index)

    @tool(args_schema=ReadSkillResourceInput)
    def read_skill_resource(name: str, relative_path: str) -> str:
        """Read a UTF-8 text resource under a skill directory (excluding SKILL.md and scripts/)."""
        return _read_skill_resource_impl(name, relative_path, frozen_index)

    @tool(args_schema=RunSkillScriptInput)
    def run_skill_script(name: str, relative_path: str, args: List[str] = []) -> str:
        """Run an executable shebang script under scripts/ for a skill directly."""
        return _run_skill_script_impl(name, relative_path, args, frozen_index)

    load_skill.name = "load_skill"  # type: ignore[attr-defined]
    read_skill_resource.name = "read_skill_resource"  # type: ignore[attr-defined]
    run_skill_script.name = "run_skill_script"  # type: ignore[attr-defined]

    return [load_skill, read_skill_resource, run_skill_script]

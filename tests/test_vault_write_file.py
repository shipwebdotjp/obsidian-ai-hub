"""Tests for the Vault direct-write capability (`vault_write_file`).

Covers the service (`web.services.vault.write_vault_file`), the AI Agent
registry tool, and the Task Agent capability derivation + adapter execution.

Operation scenario (irreversible Vault write): validated relative path and
explicit `overwrite` flag flow into one atomic temp-file + replace; invalid,
traversal, outside-Vault, conflict, and I/O failures stop without writing.
"""

import json
import os
from pathlib import Path

import pytest

from obsidian_ai_hub.agents import registry as agent_registry
from obsidian_ai_hub.tasks import capability_schemas as capability_schemas
from obsidian_ai_hub.tasks.capabilities import get_capability_definitions
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.web.services import vault as vault_service


def _invoke_tool(payload: dict) -> dict:
    return json.loads(agent_registry.vault_write_file.invoke(payload))


def _no_tmp_leftovers(vault: Path) -> None:
    leftovers = list(vault.rglob(".oaihub-tmp-*.part"))
    assert leftovers == []


def test_create_new_file():
    res = _invoke_tool({"relative_path": "notes/new-note.md", "content": "# hi\n"})
    assert res["relative_path"] == "notes/new-note.md"
    assert res["bytes_written"] == len("# hi\n".encode("utf-8"))
    assert res["overwritten"] is False
    target = Path(app_config.VAULT_PATH) / "notes" / "new-note.md"
    assert target.read_text(encoding="utf-8") == "# hi\n"
    _no_tmp_leftovers(Path(app_config.VAULT_PATH))


def test_creates_parent_directories():
    res = _invoke_tool({"relative_path": "a/b/c/deep.md", "content": "deep content"})
    assert res["relative_path"] == "a/b/c/deep.md"
    assert res["bytes_written"] == len(b"deep content")
    target = Path(app_config.VAULT_PATH) / "a" / "b" / "c" / "deep.md"
    assert target.read_text(encoding="utf-8") == "deep content"


def test_explicit_overwrite():
    _invoke_tool({"relative_path": "notes/over.md", "content": "v1"})
    res = _invoke_tool(
        {"relative_path": "notes/over.md", "content": "v2", "overwrite": True}
    )
    assert res["overwritten"] is True
    assert res["bytes_written"] == len(b"v2")
    target = Path(app_config.VAULT_PATH) / "notes" / "over.md"
    assert target.read_text(encoding="utf-8") == "v2"


def test_overwrite_denied_without_flag():
    _invoke_tool({"relative_path": "notes/keep.md", "content": "original"})
    res = _invoke_tool({"relative_path": "notes/keep.md", "content": "changed"})
    assert "error" in res
    target = Path(app_config.VAULT_PATH) / "notes" / "keep.md"
    assert target.read_text(encoding="utf-8") == "original"
    _no_tmp_leftovers(Path(app_config.VAULT_PATH))


def test_overwrite_false_is_denied_explicitly():
    _invoke_tool({"relative_path": "notes/keep2.md", "content": "original"})
    res = _invoke_tool(
        {"relative_path": "notes/keep2.md", "content": "changed", "overwrite": False}
    )
    assert "error" in res


def test_service_raises_file_exists_on_conflict():
    vault_service.write_vault_file("conflict.md", "v1")
    with pytest.raises(FileExistsError):
        vault_service.write_vault_file("conflict.md", "v2")


def test_dotdot_traversal_rejected(tmp_path: Path):
    outside = tmp_path / "outside.md"
    res = _invoke_tool({"relative_path": "../outside.md", "content": "evil"})
    assert "error" in res
    assert not outside.exists()
    res2 = _invoke_tool({"relative_path": "a/../../evil.md", "content": "evil"})
    assert "error" in res2
    assert not outside.exists()


def test_absolute_path_rejected(tmp_path: Path):
    target = tmp_path / "abs-target.md"
    res = _invoke_tool({"relative_path": str(target), "content": "evil"})
    assert "error" in res
    assert not target.exists()


def test_symlink_escape_rejected(tmp_path: Path):
    vault = Path(app_config.VAULT_PATH)
    vault.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "secret.md").write_text("secret", encoding="utf-8")
    (vault / "evil-link").symlink_to(outside_dir, target_is_directory=True)
    res = _invoke_tool({"relative_path": "evil-link/escaped.md", "content": "evil"})
    assert "error" in res
    assert not (outside_dir / "escaped.md").exists()

    # A symlink file pointing outside must not be followed either.
    (vault / "evil-file.md").symlink_to(outside_dir / "secret.md")
    res2 = _invoke_tool(
        {"relative_path": "evil-file.md", "content": "evil", "overwrite": True}
    )
    assert "error" in res2
    assert (outside_dir / "secret.md").read_text(encoding="utf-8") == "secret"


def test_utf8_content_roundtrip():
    content = "日本語のメモ 🎉\n\n- 箇条書き\n"
    res = _invoke_tool({"relative_path": "notes/utf8.md", "content": content})
    assert res["bytes_written"] == len(content.encode("utf-8"))
    target = Path(app_config.VAULT_PATH) / "notes" / "utf8.md"
    assert target.read_text(encoding="utf-8") == content
    # Read back through the existing read path.
    read_back = vault_service.get_vault_file("notes/utf8.md")
    assert read_back["content"] == content


def test_vault_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(app_config, "VAULT_PATH", "")
    res = _invoke_tool({"relative_path": "notes/x.md", "content": "hi"})
    assert "error" in res


def test_io_error_surfaced_as_tool_error():
    vault = Path(app_config.VAULT_PATH)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "blocker").write_text("i am a file", encoding="utf-8")
    res = _invoke_tool(
        {"relative_path": "blocker/child.md", "content": "cannot nest under a file"}
    )
    assert "error" in res
    assert not (vault / "blocker" / "child.md").exists()
    _no_tmp_leftovers(vault)


def test_invalid_input_types_rejected():
    with pytest.raises(TypeError):
        vault_service.write_vault_file("notes/x.md", b"bytes")  # type: ignore[arg-type]
    res = _invoke_tool({"relative_path": "", "content": "hi"})
    assert "error" in res


def test_dot_root_and_nul_paths_rejected():
    for bad in (".", "a\x00b.md"):
        res = _invoke_tool({"relative_path": bad, "content": "hi"})
        assert "error" in res, bad
    with pytest.raises(ValueError):
        vault_service.write_vault_file(".", "hi")


def test_existing_symlink_is_replaced_not_followed():
    vault = Path(app_config.VAULT_PATH)
    vault.mkdir(parents=True, exist_ok=True)
    real = vault / "real-target.md"
    real.write_text("real content", encoding="utf-8")
    link = vault / "link-note.md"
    link.symlink_to(real)
    res = _invoke_tool(
        {"relative_path": "link-note.md", "content": "new", "overwrite": True}
    )
    assert res["overwritten"] is True
    # The link itself is replaced; the link target is never modified.
    assert real.read_text(encoding="utf-8") == "real content"
    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "new"


def test_broken_symlink_outside_rejected_even_with_overwrite(tmp_path: Path):
    vault = Path(app_config.VAULT_PATH)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "dangling.md").symlink_to(tmp_path / "no-such-dir" / "x.md")
    res = _invoke_tool(
        {"relative_path": "dangling.md", "content": "evil", "overwrite": True}
    )
    assert "error" in res
    assert (vault / "dangling.md").is_symlink()


def test_broken_symlink_inside_replaced_with_overwrite():
    vault = Path(app_config.VAULT_PATH)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "inner-dangling.md").symlink_to(vault / "never-created.md")
    res = _invoke_tool(
        {"relative_path": "inner-dangling.md", "content": "fixed", "overwrite": True}
    )
    assert res["overwritten"] is True
    target = vault / "inner-dangling.md"
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "fixed"


def test_concurrent_create_is_not_overwritten(monkeypatch: pytest.MonkeyPatch):
    """A file created between our existence check and replace must survive.

    Simulates the losing side of a create race by creating the target inside
    a racing ``os.open`` wrapper: the atomic O_EXCL claim must then fail and
    the concurrent content must be preserved.
    """
    real_open = os.open
    vault = Path(app_config.VAULT_PATH)
    sentinel = "concurrent winner"
    raced: list[str] = []

    def racing_open(path, flags, *args, **kwargs):
        if str(path).endswith(os.path.join("race", "note.md")) and not raced:
            raced.append(str(path))
            (vault / "race").mkdir(parents=True, exist_ok=True)
            (vault / "race" / "note.md").write_text(sentinel, encoding="utf-8")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)
    res = _invoke_tool({"relative_path": "race/note.md", "content": "loser"})
    assert "error" in res
    assert "already exists" in res["error"]
    assert raced
    assert (vault / "race" / "note.md").read_text(encoding="utf-8") == sentinel
    _no_tmp_leftovers(vault)


def test_ai_agent_registry_exposes_tool():
    assert "vault_write_file" in agent_registry.TOOL_DEFINITIONS
    assert "vault_write_file" in {
        t["tool_id"] for t in agent_registry.list_available_tools()
    }
    resolved = agent_registry.resolve_tools(["vault_write_file"])
    assert len(resolved) == 1
    assert resolved[0].name == "vault_write_file"
    res = json.loads(resolved[0].invoke({"relative_path": "r.md", "content": "x"}))
    assert res["relative_path"] == "r.md"


def test_task_capability_derived_with_plan_required_policy():
    by_key = {d.key: d for d in get_capability_definitions()}
    definition = by_key["vault_write_file"]
    assert definition.adapter_kind == "registry_tool"
    assert definition.registry_tool_id == "vault_write_file"
    # Vault writes are irreversible: Task plans must require approval.
    assert definition.default_approval_policy == "plan_required"

    model = capability_schemas.resolve_input_model("vault_write_file")
    assert model is agent_registry.VaultWriteFileInput
    validated = capability_schemas.validate_capability_inputs(
        "vault_write_file",
        {"relative_path": "notes/task.md", "content": "hi", "overwrite": False},
    )
    assert validated["relative_path"] == "notes/task.md"
    with pytest.raises(ValueError, match="inputs invalid"):
        capability_schemas.validate_capability_inputs(
            "vault_write_file",
            {"relative_path": "notes/task.md", "content": "hi", "unknown": 1},
        )


def test_task_adapter_executes_write_end_to_end():
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.adapters import get_default_executor

    task = task_store.create_task("write a vault note")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "write note",
            "steps": [
                {
                    "capability_key": "vault_write_file",
                    "title": "write",
                    "target": {},
                    "inputs": {
                        "relative_path": "task-agent/note.md",
                        "content": "from task",
                    },
                    "side_effects": "vault write",
                }
            ],
            "completion_criteria": "done",
        },
        {"vault_write_file": "plan_required"},
    )
    result = get_default_executor().execute_step(
        task, plan, 0, plan["plan"]["steps"][0]
    )
    assert result.capability_key == "vault_write_file"
    summary = json.loads(result.summary)
    assert summary["relative_path"] == "task-agent/note.md"
    target = Path(app_config.VAULT_PATH) / "task-agent" / "note.md"
    assert target.read_text(encoding="utf-8") == "from task"

    # A conflicting re-run without overwrite fails instead of overwriting.
    plan2 = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "rewrite note",
            "steps": [
                {
                    "capability_key": "vault_write_file",
                    "title": "rewrite",
                    "target": {},
                    "inputs": {
                        "relative_path": "task-agent/note.md",
                        "content": "changed",
                    },
                    "side_effects": "vault write",
                }
            ],
            "completion_criteria": "done",
        },
        {"vault_write_file": "plan_required"},
    )
    # The registry tool reports conflicts as an error payload (not an
    # exception), so the adapter surfaces it in the summary; the file stays.
    conflict = get_default_executor().execute_step(
        task, plan2, 0, plan2["plan"]["steps"][0]
    )
    assert "already exists" in conflict.summary
    assert target.read_text(encoding="utf-8") == "from task"


def test_adapter_rejects_unknown_inputs_before_writing():
    from obsidian_ai_hub.tasks import store as task_store
    from obsidian_ai_hub.tasks.adapters import get_default_executor

    task = task_store.create_task("bad inputs")
    plan = task_store.create_plan(
        task["task_id"],
        {
            "purpose": "bad",
            "steps": [
                {
                    "capability_key": "vault_write_file",
                    "title": "bad",
                    "target": {},
                    "inputs": {"relative_path": "x.md"},
                    "side_effects": "vault write",
                }
            ],
            "completion_criteria": "done",
        },
        {"vault_write_file": "plan_required"},
    )
    with pytest.raises(ValueError, match="inputs invalid"):
        get_default_executor().execute_step(task, plan, 0, plan["plan"]["steps"][0])
    assert not (Path(app_config.VAULT_PATH) / "x.md").exists()

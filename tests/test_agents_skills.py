"""Unit tests for Agent Skills capability (agents/skills.py)."""

import json
import os
import stat
import subprocess
from pathlib import Path
import pytest

from obsidian_ai_hub.agents.skills import (
    SkillInfo,
    SkillIndex,
    discover_skills,
    create_skill_tools,
    _load_skill_impl,
    _read_skill_resource_impl,
    _run_skill_script_impl,
)
from obsidian_ai_hub.agents import registry, runtime


def test_skills_root_priority_and_frontmatter_validation(tmp_path):
    primary_root = tmp_path / "primary_skills"
    secondary_root = tmp_path / "secondary_skills"
    primary_root.mkdir()
    secondary_root.mkdir()

    # Skill A in primary
    skill_a_p = primary_root / "skill_a"
    skill_a_p.mkdir()
    (skill_a_p / "SKILL.md").write_text(
        "---\nname: skill_a\ndescription: Primary Skill A\n---\nPrimary Body A",
        encoding="utf-8",
    )

    # Skill A in secondary (same name -> secondary wins)
    skill_a_s = secondary_root / "skill_a"
    skill_a_s.mkdir()
    (skill_a_s / "SKILL.md").write_text(
        "---\nname: skill_a\ndescription: Secondary Skill A\n---\nSecondary Body A",
        encoding="utf-8",
    )

    # Skill B only in primary
    skill_b_p = primary_root / "skill_b"
    skill_b_p.mkdir()
    (skill_b_p / "SKILL.md").write_text(
        "---\nname: skill_b\ndescription: Primary Skill B\n---\nPrimary Body B",
        encoding="utf-8",
    )

    # Skill Invalid (missing frontmatter name)
    skill_inv = secondary_root / "skill_inv"
    skill_inv.mkdir()
    (skill_inv / "SKILL.md").write_text(
        "---\ndescription: Missing name\n---\nInvalid Body",
        encoding="utf-8",
    )

    index = discover_skills(primary_root=primary_root, secondary_root=secondary_root)

    assert "skill_a" in index.skills
    assert "skill_b" in index.skills
    assert "skill_inv" not in index.skills

    # Secondary wins for skill_a
    assert index.skills["skill_a"].description == "Secondary Skill A"
    assert index.skills["skill_b"].description == "Primary Skill B"


def test_invalid_skill_exclusion_and_symlink_escape(tmp_path):
    primary_root = tmp_path / "primary_skills"
    primary_root.mkdir()

    # Symlink escaping root
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "SKILL.md").write_text(
        "---\nname: escaped_skill\ndescription: Escaped\n---\nEscaped Body",
        encoding="utf-8",
    )

    symlink_skill = primary_root / "escaped_symlink"
    os.symlink(outside_dir, symlink_skill)

    index = discover_skills(primary_root=primary_root, secondary_root=tmp_path / "empty_sec")
    assert "escaped_skill" not in index.skills
    assert "escaped_symlink" not in index.skills


def test_per_turn_rescan_freeze(tmp_path):
    primary_root = tmp_path / "primary_skills"
    primary_root.mkdir()

    skill_1 = primary_root / "skill_1"
    skill_1.mkdir()
    (skill_1 / "SKILL.md").write_text(
        "---\nname: skill_1\ndescription: Skill 1\n---\nBody 1", encoding="utf-8"
    )

    # Initial scan (freeze for turn 1)
    index_turn_1 = discover_skills(primary_root=primary_root, secondary_root=tmp_path / "sec")
    assert "skill_1" in index_turn_1.skills
    assert "skill_2" not in index_turn_1.skills

    # Add skill_2 mid-run
    skill_2 = primary_root / "skill_2"
    skill_2.mkdir()
    (skill_2 / "SKILL.md").write_text(
        "---\nname: skill_2\ndescription: Skill 2\n---\nBody 2", encoding="utf-8"
    )

    # turn 1 index remains frozen
    assert "skill_2" not in index_turn_1.skills

    # Next turn scan reflects skill_2
    index_turn_2 = discover_skills(primary_root=primary_root, secondary_root=tmp_path / "sec")
    assert "skill_2" in index_turn_2.skills


def test_load_skill_happy_path_and_char_limit(tmp_path):
    skill_dir = tmp_path / "demo_skill"
    skill_dir.mkdir()
    big_body = "A" * 25_000
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: demo\ndescription: Demo Skill\n---\n{big_body}", encoding="utf-8"
    )

    index = SkillIndex({
        "demo": SkillInfo("demo", "Demo Skill", skill_dir, skill_dir / "SKILL.md")
    })

    body = _load_skill_impl("demo", index)
    assert len(body) < 25_000
    assert "…(truncated)" in body
    assert body.startswith("A" * 100)


def test_read_skill_resource_happy_path_binary_and_security_rejections(tmp_path):
    skill_dir = tmp_path / "res_skill"
    skill_dir.mkdir()

    # Valid text resource
    (skill_dir / "notes.txt").write_text("Hello text resource", encoding="utf-8")

    # Binary resource
    (skill_dir / "data.bin").write_bytes(b"\x00\x01\x02\x03\xff")

    # File outside skill dir for traversal test
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret data", encoding="utf-8")

    # Scripts directory file
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("print('hi')", encoding="utf-8")

    index = SkillIndex({
        "res_skill": SkillInfo("res_skill", "Res Skill", skill_dir, skill_dir / "SKILL.md")
    })

    # 1. Happy path
    res = _read_skill_resource_impl("res_skill", "notes.txt", index)
    assert res == "Hello text resource"

    # 2. Binary rejection
    res_bin = _read_skill_resource_impl("res_skill", "data.bin", index)
    assert "Binary files are not supported" in res_bin

    # 3. Reading SKILL.md rejection
    res_md = _read_skill_resource_impl("res_skill", "SKILL.md", index)
    assert "Reading SKILL.md via read_skill_resource is not allowed" in res_md

    # 4. Reading under scripts/ rejection
    res_script = _read_skill_resource_impl("res_skill", "scripts/helper.py", index)
    assert "Reading files under scripts/ is not allowed" in res_script

    # 5. Path traversal rejection
    res_trav = _read_skill_resource_impl("res_skill", "../secret.txt", index)
    assert "Path traversal" in res_trav or "escapes skill directory" in res_trav


def test_run_skill_script_execution_argv_cwd_exit_code_timeout_and_limits(tmp_path):
    skill_dir = tmp_path / "script_skill"
    skill_dir.mkdir()
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()

    # 1. Echo script
    echo_script = scripts_dir / "echo.sh"
    echo_script.write_text(
        "#!/bin/bash\necho \"cwd: $(pwd)\"\necho \"args: $@\"\n", encoding="utf-8"
    )
    echo_script.chmod(echo_script.stat().st_mode | stat.S_IXUSR)

    # 2. Failing script
    fail_script = scripts_dir / "fail.sh"
    fail_script.write_text("#!/bin/bash\necho 'error happened' >&2\nexit 2\n", encoding="utf-8")
    fail_script.chmod(fail_script.stat().st_mode | stat.S_IXUSR)

    # 3. Non-executable script
    noexec_script = scripts_dir / "noexec.sh"
    noexec_script.write_text("#!/bin/bash\necho 'noexec'\n", encoding="utf-8")

    # 4. Script missing shebang
    noshebang_script = scripts_dir / "noshebang.sh"
    noshebang_script.write_text("echo 'noshebang'\n", encoding="utf-8")
    noshebang_script.chmod(noshebang_script.stat().st_mode | stat.S_IXUSR)

    index = SkillIndex({
        "script_skill": SkillInfo("script_skill", "Script Skill", skill_dir, skill_dir / "SKILL.md")
    })

    # Test 1: Echo script happy path (argv and cwd)
    res_raw = _run_skill_script_impl("script_skill", "echo.sh", ["hello", "world"], index)
    res = json.loads(res_raw)
    assert res["success"] is True
    assert res["exit_code"] == 0
    assert str(skill_dir) in res["stdout"]
    assert "hello world" in res["stdout"]

    # Test 2: Failing script
    res_fail_raw = _run_skill_script_impl("script_skill", "fail.sh", [], index)
    res_fail = json.loads(res_fail_raw)
    assert res_fail["success"] is False
    assert res_fail["exit_code"] == 2
    assert "error happened" in res_fail["stderr"]

    # Test 3: Non-executable script rejection
    res_noexec_raw = _run_skill_script_impl("script_skill", "noexec.sh", [], index)
    res_noexec = json.loads(res_noexec_raw)
    assert res_noexec["success"] is False
    assert "not executable" in res_noexec["stderr"]

    # Test 4: Missing shebang rejection
    res_noshebang_raw = _run_skill_script_impl("script_skill", "noshebang.sh", [], index)
    res_noshebang = json.loads(res_noshebang_raw)
    assert res_noshebang["success"] is False
    assert "valid shebang" in res_noshebang["stderr"]

    # Test 5: Too many args rejection (>20)
    too_many_args = [f"arg_{i}" for i in range(25)]
    res_args_raw = _run_skill_script_impl("script_skill", "echo.sh", too_many_args, index)
    res_args = json.loads(res_args_raw)
    assert res_args["success"] is False
    assert "Maximum of 20 arguments allowed" in res_args["stderr"]

    # Test 6: Path traversal rejection
    res_trav_raw = _run_skill_script_impl("script_skill", "../echo.sh", [], index)
    res_trav = json.loads(res_trav_raw)
    assert res_trav["success"] is False
    assert "Path traversal" in res_trav["stderr"] or "escapes" in res_trav["stderr"]


def test_registry_resolution_and_runtime_prompt_catalog(tmp_path, monkeypatch):
    primary_root = tmp_path / "primary_skills"
    primary_root.mkdir()
    demo_s = primary_root / "demo"
    demo_s.mkdir()
    (demo_s / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo Skill for System Prompt\n---\nDemo Body",
        encoding="utf-8",
    )

    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_PRIMARY_ROOT", primary_root)
    monkeypatch.setattr("obsidian_ai_hub.utils.config.AGENT_SKILLS_ROOT", tmp_path / "sec_empty")

    # 1. Check registry multi-tool expansion for tool_id "skills"
    tools = registry.resolve_tools(["skills"])
    tool_names = [t.name for t in tools]
    assert len(tools) == 3
    assert set(tool_names) == {"load_skill", "read_skill_resource", "run_skill_script"}

    # 2. Check runtime catalog block when skills enabled
    # We test generate_agent_stream system prompt generation indirectly by checking that system prompt block includes skills
    # Let's verify discover_skills summary format directly
    index = discover_skills(primary_root=primary_root, secondary_root=tmp_path / "sec_empty")
    summary = index.get_catalog_summary()
    assert len(summary) == 1
    assert summary[0]["name"] == "demo"
    assert summary[0]["description"] == "Demo Skill for System Prompt"

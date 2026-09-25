"""Vault write CLI wrapper (``vault_ops.main_vault_write``)."""

from __future__ import annotations

import json

from obsidian_ai_hub import vault_ops
from obsidian_ai_hub.web.services.vault import get_vault_file


def test_vault_write_reads_content_file(tmp_path, capsys):
    source = tmp_path / "content.md"
    source.write_text("body", encoding="utf-8")

    assert vault_ops.main_vault_write("notes/cli.md", str(source), False) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["relative_path"] == "notes/cli.md"
    assert get_vault_file("notes/cli.md")["content"] == "body"


def test_vault_write_existing_without_overwrite_fails(tmp_path, capsys):
    source = tmp_path / "content.md"
    source.write_text("body", encoding="utf-8")

    assert vault_ops.main_vault_write("notes/dup.md", str(source), False) == 0
    capsys.readouterr()

    assert vault_ops.main_vault_write("notes/dup.md", str(source), False) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False

    assert vault_ops.main_vault_write("notes/dup.md", str(source), True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["overwritten"] is True


def test_vault_write_rejects_non_markdown(tmp_path, capsys):
    source = tmp_path / "content.md"
    source.write_text("body", encoding="utf-8")

    assert vault_ops.main_vault_write("notes/x.txt", str(source), False) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False


def test_vault_write_reports_missing_content_file(tmp_path, capsys):
    assert (
        vault_ops.main_vault_write(
            "notes/x.md", str(tmp_path / "missing.md"), False
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False


def test_vault_write_rejects_path_traversal(tmp_path, capsys):
    source = tmp_path / "content.md"
    source.write_text("body", encoding="utf-8")

    assert vault_ops.main_vault_write("../escape.md", str(source), False) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False

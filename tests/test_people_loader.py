from __future__ import annotations

import pytest
from pathlib import Path

from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.utils.people_loader import load_and_validate_people_notes, load_people_notes_with_report


def test_people_loader_no_dir(tmp_path, monkeypatch):
    # Set PEOPLE_PATH to a non-existent directory
    fake_people_path = tmp_path / "non_existent_people_dir"
    monkeypatch.setattr(app_config, "PEOPLE_PATH", fake_people_path)

    res, report = load_people_notes_with_report()
    assert res == {}
    assert report["file_deficiencies"] == []


def test_people_loader_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    # Note 1: Yamada
    note1 = tmp_path / "yamada.md"
    note1.write_text("""---
id: yamada-taro
name: 山田太郎
aliases:
  - 山田君
  - たろう
---
Yamada's description
""", encoding="utf-8")

    # Note 2: Sato
    note2 = tmp_path / "sato.md"
    note2.write_text("""---
id: sato-hanako
name: 佐藤花子
aliases:
  - はなちゃん
---
Sato's description
""", encoding="utf-8")

    res, report = load_people_notes_with_report()

    # Match normalized names/aliases
    assert "山田太郎" in res or "山田太郎".lower() in res
    assert "山田君" in res or "山田君".lower() in res
    assert "佐藤花子" in res or "佐藤花子".lower() in res
    assert "はなちゃん" in res or "はなちゃん".lower() in res

    yamada_record = res["山田太郎".lower()]
    assert yamada_record["id"] == "yamada-taro"
    assert yamada_record["name"] == "山田太郎"
    assert "山田君" in yamada_record["aliases"]

    sato_record = res["佐藤花子".lower()]
    assert sato_record["id"] == "sato-hanako"

    assert report["file_deficiencies"] == []
    assert report["duplicate_ids"] == []
    assert report["normalized_name_collisions"] == []
    assert report["alias_collisions"] == []


def test_people_loader_missing_id(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    note = tmp_path / "invalid.md"
    note.write_text("""---
name: No ID Person
---
""", encoding="utf-8")

    res, report = load_people_notes_with_report()
    assert res == {}
    assert len(report["file_deficiencies"]) == 1
    assert "Missing or empty required field 'id'" in report["file_deficiencies"][0]["message"]


def test_people_loader_missing_name(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    note = tmp_path / "invalid.md"
    note.write_text("""---
id: valid-id
---
""", encoding="utf-8")

    res, report = load_people_notes_with_report()
    assert res == {}
    assert len(report["file_deficiencies"]) == 1
    assert "Missing or empty required field 'name'" in report["file_deficiencies"][0]["message"]


def test_people_loader_duplicate_id(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    note1 = tmp_path / "yamada1.md"
    note1.write_text("""---
id: yamada-taro
name: 山田太郎
---
""", encoding="utf-8")

    note2 = tmp_path / "yamada2.md"
    note2.write_text("""---
id: yamada-taro
name: 別の山田太郎
---
""", encoding="utf-8")

    res, report = load_people_notes_with_report()
    assert res == {}
    assert len(report["duplicate_ids"]) == 1
    assert report["duplicate_ids"][0]["id"] == "yamada-taro"
    assert len(report["duplicate_ids"][0]["paths"]) == 2


def test_people_loader_duplicate_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    note1 = tmp_path / "yamada.md"
    note1.write_text("""---
id: yamada-taro
name: 山田太郎
aliases:
  - ヤマダ
---
""", encoding="utf-8")

    note2 = tmp_path / "yamada_clone.md"
    note2.write_text("""---
id: yamada-jiro
name: 山田二郎
aliases:
  - ヤマダ
---
""", encoding="utf-8")

    res, report = load_people_notes_with_report()

    # Main names should still be mapped, but duplicate alias 'ヤマダ' is excluded
    assert "山田太郎" in res or "山田太郎".lower() in res
    assert "山田二郎" in res or "山田二郎".lower() in res
    assert "ヤマダ" not in res and "ヤマダ".lower() not in res

    assert len(report["alias_collisions"]) == 1
    assert report["alias_collisions"][0]["alias"] == "ヤマダ".lower()
    assert len(report["alias_collisions"][0]["notes"]) == 2


def test_people_loader_invalid_types_id_name(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "PEOPLE_PATH", tmp_path)

    # Note with integer ID (should be rejected as it's not a string)
    note1 = tmp_path / "integer_id.md"
    note1.write_text("""---
id: 12345
name: Number ID Person
---
""", encoding="utf-8")

    res, report = load_people_notes_with_report()
    assert res == {}
    assert len(report["file_deficiencies"]) == 1
    assert "Missing or empty required field 'id'" in report["file_deficiencies"][0]["message"]

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub import sync_people


def test_sync_people_integration(test_memory_db_path, tmp_path, monkeypatch):
    # Setup temporary PEOPLE_PATH
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(app_config, "PEOPLE_PATH", people_dir)

    conn = memory.get_db_connection()
    try:
        # Create summary with unresolved candidates
        # 1. 山田君 (unresolved)
        # 2. 佐藤さん (unresolved)
        record = {
            "period_type": "day",
            "period_key": "2026-07-21",
            "period_start": "2026-07-21",
            "period_end": "2026-07-21",
            "summary": "Met guest observers",
            "people": [
                {"name": "山田君", "note": "he observed today's event"},
                {"name": "佐藤さん", "note": "spoke during the presentation"},
            ]
        }
        summary_store.upsert_summary(record, conn=conn)

        # Retrieve and verify unresolved candidate records exist
        got = summary_store.get_summary_by_period("day", "2026-07-21", conn=conn)
        assert len(got["people"]) == 2
        yamada_p = [p for p in got["people"] if p["name"] == "山田君"][0]
        assert yamada_p["resolution_status"] == "unresolved"
        assert yamada_p["candidate_id"] is not None

        sato_p = [p for p in got["people"] if p["name"] == "佐藤さん"][0]
        assert sato_p["resolution_status"] == "unresolved"
        assert sato_p["candidate_id"] is not None

        # Also create an old people record with vault_id NULL to test old people merging
        # This one has the same name "山田太郎" and will be adopted as the master resolved person_id
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_old_yamada", "山田太郎", "山田太郎", None)
        )
        conn.execute(
            "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
            (got["summary_id"], "peo_old_yamada", "old yamada note", 10)
        )

        # This one has the alias name "山田君" and will be merged into the master and deleted
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_old_yamada_alias", "山田君", "山田君", None)
        )
        conn.execute(
            "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
            (got["summary_id"], "peo_old_yamada_alias", "old alias note", 5)
        )

        # Now, write the Vault people note for Yamada and Sato
        note1 = people_dir / "yamada.md"
        note1.write_text("""---
id: yamada-taro
name: 山田太郎
aliases:
  - 山田君
  - たろう
---
Official Yamada note.
""", encoding="utf-8")

        note2 = people_dir / "sato.md"
        note2.write_text("""---
id: sato-hanako
name: 佐藤花子
aliases:
  - 佐藤さん
---
Official Sato note.
""", encoding="utf-8")

        conn.commit()
    finally:
        conn.close()

    # Execute people sync
    sync_people.main()

    conn = memory.get_db_connection()
    try:
        # Retrieve summary again to verify resolution
        got_after = summary_store.get_summary_by_period("day", "2026-07-21", conn=conn)
        assert len(got_after["people"]) == 2  # 山田君 and 山田太郎 merged into one!

        p_yamada = [p for p in got_after["people"] if p["name"] == "山田太郎"][0]
        assert p_yamada["resolution_status"] == "resolved"
        # Notes are joined, minimum display order is preserved (山田君 was index 0, old Yamada was 10)
        assert p_yamada["display_order"] == 0
        assert "he observed today's event" in p_yamada["note"]
        assert "old yamada note" in p_yamada["note"]
        assert "old alias note" in p_yamada["note"]

        p_sato = [p for p in got_after["people"] if p["name"] == "佐藤花子"][0]
        assert p_sato["resolution_status"] == "resolved"
        assert p_sato["display_order"] == 1
        assert p_sato["note"] == "spoke during the presentation"

        # Check that candidates are deleted from database
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM person_candidates")
        assert cursor.fetchone()[0] == 0

        # Check that the adopted master person is kept
        cursor.execute("SELECT count(*) FROM people WHERE person_id = 'peo_old_yamada' AND vault_id = 'yamada-taro'")
        assert cursor.fetchone()[0] == 1

        # Check that old duplicate alias people record is deleted
        cursor.execute("SELECT count(*) FROM people WHERE person_id = 'peo_old_yamada_alias'")
        assert cursor.fetchone()[0] == 0

    finally:
        conn.close()

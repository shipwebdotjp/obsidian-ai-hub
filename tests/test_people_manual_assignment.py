from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web import service


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def test_manual_assignment_flow(test_memory_db_path, client):
    conn = memory.get_db_connection()
    try:
        # Create a Vault-linked person (鈴木健)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_suzuki", "鈴木健", "鈴木健", "suzuki-ken"),
        )
        # Create an unlinked person (佐藤太郎)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_sato", "佐藤太郎", "佐藤太郎", None),
        )
        # Create a candidate (山田さん)
        conn.execute(
            "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
            ("cand_yamada", "山田さん", "山田さん", "unresolved"),
        )
        # Create two summaries
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "Summary 1"),
        )
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("sum_2", "day", "2026-08-02", "2026-08-02", "2026-08-02", "Summary 2"),
        )
        # Link candidate to both summaries
        conn.execute(
            "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
            ("sum_1", "cand_yamada", "山田ノート1", 3),
        )
        conn.execute(
            "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
            ("sum_2", "cand_yamada", "山田ノート2", 5),
        )
        conn.commit()
    finally:
        conn.close()

    # Get candidate detail
    response = client.get("/api/v1/people/candidates/cand_yamada")
    assert response.status_code == 200
    detail = response.json()
    assert detail["assigned_summaries_count"] == 0

    # Case 1: Try assigning to unlinked person (peo_sato) -> Should reject with 400
    response = client.post(
        "/api/v1/people/candidates/cand_yamada/summaries/sum_1/assign",
        json={"target_person_id": "peo_sato"},
    )
    assert response.status_code == 400
    # Verify DB has no manual assignment stored
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM summary_person_assignments WHERE summary_id = 'sum_1' AND normalized_name = '山田さん'"
        )
        assert cursor.fetchone()[0] == 0
    finally:
        conn.close()

    # Case 2: Assign sum_1 to Vault-linked person (peo_suzuki) -> Should succeed
    response = client.post(
        "/api/v1/people/candidates/cand_yamada/summaries/sum_1/assign",
        json={"target_person_id": "peo_suzuki"},
    )
    assert response.status_code == 200

    conn = memory.get_db_connection()
    try:
        # Check manual assignment is saved
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM summary_person_assignments WHERE summary_id = 'sum_1' AND normalized_name = '山田さん'"
        )
        assignment = cursor.fetchone()
        assert assignment is not None
        assert assignment["person_id"] == "peo_suzuki"

        # Check candidate link is removed from sum_1
        cursor.execute(
            "SELECT * FROM summary_person_candidates WHERE summary_id = 'sum_1' AND candidate_id = 'cand_yamada'"
        )
        assert cursor.fetchone() is None

        # Check target person sum_1 link is created
        cursor.execute(
            "SELECT * FROM summary_people WHERE summary_id = 'sum_1' AND person_id = 'peo_suzuki'"
        )
        sum_link = cursor.fetchone()
        assert sum_link is not None
        assert sum_link["note"] == "山田ノート1"
        assert sum_link["display_order"] == 3

        # Candidate should still exist because sum_2 link is still unresolved
        cursor.execute(
            "SELECT * FROM person_candidates WHERE candidate_id = 'cand_yamada'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()

    # Get candidate detail again to check assigned_summaries_count has updated to 1
    response = client.get("/api/v1/people/candidates/cand_yamada")
    assert response.status_code == 200
    detail = response.json()
    assert detail["assigned_summaries_count"] == 1

    # Case 3: Try resolving candidate with manual assignments via the global/bulk resolution API -> Should reject with 409
    response = client.post(
        "/api/v1/people/candidates/cand_yamada/resolve",
        json={"target_person_id": "peo_suzuki"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["conflict_type"] == "assignment_conflict"

    # Case 4: Assign sum_2 to Vault-linked person (peo_suzuki) -> Should succeed
    response = client.post(
        "/api/v1/people/candidates/cand_yamada/summaries/sum_2/assign",
        json={"target_person_id": "peo_suzuki"},
    )
    assert response.status_code == 200

    conn = memory.get_db_connection()
    try:
        # Candidate should now be deleted since no unresolved links remain
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM person_candidates WHERE candidate_id = 'cand_yamada'"
        )
        assert cursor.fetchone() is None
    finally:
        conn.close()


def test_upsert_summary_prioritizes_manual_assignments(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        # Create Vault-linked person (鈴木健)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_suzuki", "鈴木健", "鈴木健", "suzuki-ken"),
        )
        # Create another Vault-linked person (佐藤太郎)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_sato", "佐藤太郎", "佐藤太郎", "sato-taro"),
        )
        # Add a confirmed alias mapping '山田さん' -> Sato
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("山田さん", "peo_sato", "山田さん"),
        )
        # Set up a summary "sum_1"
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "Summary 1"),
        )
        # Add manual assignment '山田さん' -> Suzuki (peo_suzuki) specifically for "sum_1"
        conn.execute(
            "INSERT INTO summary_person_assignments (summary_id, normalized_name, person_id) VALUES (?, ?, ?)",
            ("sum_1", "山田さん", "peo_suzuki"),
        )
        conn.commit()
    finally:
        conn.close()

    # Re-generate/Upsert "sum_1" with people = [{'name': '山田さん'}]
    record = {
        "period_type": "day",
        "period_key": "2026-08-01",
        "period_start": "2026-08-01",
        "period_end": "2026-08-01",
        "summary": "Updated summary with Yamda-san",
        "people": [{"name": "山田さん", "note": "手動割当確認メモ"}],
    }

    # Upserting sum_1
    summary_store.upsert_summary(record)

    conn = memory.get_db_connection()
    try:
        # '山田さん' should resolve to peo_suzuki (Priority 0: manual assignment)
        # instead of peo_sato (Priority 1: confirmed global alias)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM summary_people WHERE summary_id = 'sum_1'")
        links = cursor.fetchall()
        assert len(links) == 1
        assert links[0]["person_id"] == "peo_suzuki"
        assert links[0]["note"] == "手動割当確認メモ"
    finally:
        conn.close()


def test_sync_skips_auto_absorption_for_manually_assigned_candidates(
    test_memory_db_path, tmp_path, monkeypatch
):
    # Setup temporary PEOPLE_PATH
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(app_config, "PEOPLE_PATH", people_dir)

    # 1. Create a person note in Vault for 山田太郎 with id 'yamada-taro'
    note_path = people_dir / "yamada.md"
    note_path.write_text(
        """---
id: yamada-taro
name: 山田太郎
aliases:
  - 山田さん
---
""",
        encoding="utf-8",
    )

    conn = memory.get_db_connection()
    try:
        # Setup 山田さん as candidate
        conn.execute(
            "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
            ("cand_yamada", "山田さん", "山田さん", "unresolved"),
        )
        # Create summary
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "Summary 1"),
        )
        # Link candidate to sum_1
        conn.execute(
            "INSERT INTO summary_person_candidates (summary_id, candidate_id, note, display_order) VALUES (?, ?, ?, ?)",
            ("sum_1", "cand_yamada", "山田ノート1", 3),
        )
        # Add manual assignment of '山田さん' to some other person peo_other (so candidate '山田さん' has manual assignments)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_other", "鈴木健", "鈴木健", "suzuki-ken"),
        )
        conn.execute(
            "INSERT INTO summary_person_assignments (summary_id, normalized_name, person_id) VALUES (?, ?, ?)",
            ("sum_1", "山田さん", "peo_other"),
        )
        conn.commit()
    finally:
        conn.close()

    # Trigger Sync
    service.sync_people()

    conn = memory.get_db_connection()
    try:
        # Candidate '山田さん' (cand_yamada) should NOT be absorbed/deleted
        # because it has manual assignments.
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM person_candidates WHERE candidate_id = 'cand_yamada'"
        )
        assert cursor.fetchone() is not None

        # The link to sum_1 should still exist in summary_person_candidates
        cursor.execute(
            "SELECT * FROM summary_person_candidates WHERE summary_id = 'sum_1' AND candidate_id = 'cand_yamada'"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_merge_people_transfers_manual_assignments(test_memory_db_path):
    conn = memory.get_db_connection()
    try:
        # Create unlinked person A (山田太郎)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_a", "山田太郎", "山田太郎", None),
        )
        # Create Vault-linked person B (鈴木健)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_b", "鈴木健", "鈴木健", "suzuki-ken"),
        )
        # Create summary
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, summary) VALUES (?, ?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "Summary 1"),
        )
        # Manual assignment pointing to peo_a
        conn.execute(
            "INSERT INTO summary_person_assignments (summary_id, normalized_name, person_id) VALUES (?, ?, ?)",
            ("sum_1", "山田太郎", "peo_a"),
        )
        conn.commit()
    finally:
        conn.close()

    # Execute merge (peo_a into peo_b)
    success = service.merge_people("peo_a", "peo_b")
    assert success is True

    conn = memory.get_db_connection()
    try:
        # Check manual assignment was transferred to peo_b
        cursor = conn.cursor()
        cursor.execute(
            "SELECT person_id FROM summary_person_assignments WHERE summary_id = 'sum_1' AND normalized_name = '山田太郎'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["person_id"] == "peo_b"
    finally:
        conn.close()


def test_schema_verification_migration(test_memory_db_path):
    # This verifies the schema upgrade / migration v8 logic directly using test_memory_db_path
    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA user_version;")
        assert cursor.fetchone()[0] == 20

        # Ensure summary_person_assignments table exists with correct index
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='summary_person_assignments';"
        )
        assert cursor.fetchone() is not None
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_spa_normalized_name';"
        )
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_duplicate_person_resolutions_note_concatenation(test_memory_db_path):
    # Regression test verifying that when multiple candidate/resolved/assigned notations
    # resolve to the same person_id inside the same summary, seen_person_ids does NOT
    # skip it entirely, but instead concatenates the note and preserves both notes.
    conn = memory.get_db_connection()
    try:
        # 1. Create person (鈴木健)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_suzuki", "鈴木健", "鈴木健", "suzuki-ken"),
        )
        # Create summary first to satisfy summary_person_assignments FK constraint
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end) VALUES (?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01"),
        )
        # 2. Add manual assignment mapping '山田さん' -> Suzuki for sum_1
        conn.execute(
            "INSERT INTO summary_person_assignments (summary_id, normalized_name, person_id) VALUES (?, ?, ?)",
            ("sum_1", "山田さん", "peo_suzuki"),
        )
        # 3. Add confirmed alias mapping 'A-chan' -> Suzuki
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("a-chan", "peo_suzuki", "A-chan"),
        )
        # 4. Add confirmed alias mapping '鈴木健' -> Suzuki
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("鈴木健", "peo_suzuki", "鈴木健"),
        )
        conn.commit()
    finally:
        conn.close()

    # Create sum_1 record that has:
    # - "山田さん" (which resolves to Suzuki via Priority 0 manual assignment)
    # - "A-chan" (which resolves to Suzuki via Priority 1 confirmed alias)
    # - "鈴木健" (which resolves to Suzuki via Priority 2 safe vault matching)
    record = {
        "period_type": "day",
        "period_key": "2026-08-01",
        "period_start": "2026-08-01",
        "period_end": "2026-08-01",
        "summary": "Meeting summary",
        "people": [
            {"name": "山田さん", "note": "手動割当メモ"},
            {"name": "A-chan", "note": "別名メモ"},
            {"name": "鈴木健", "note": "正規名メモ"},
        ],
    }

    # Upsert summary
    summary_store.upsert_summary(record)

    conn = memory.get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM summary_people WHERE summary_id = 'sum_1'")
        rows = cursor.fetchall()

        # Only 1 unique row in summary_people for peo_suzuki
        assert len(rows) == 1
        assert rows[0]["person_id"] == "peo_suzuki"

        # The notes from all three notations should be concatenated with newlines, preserving all information
        note = rows[0]["note"]
        assert "手動割当メモ" in note
        assert "別名メモ" in note
        assert "正規名メモ" in note
    finally:
        conn.close()

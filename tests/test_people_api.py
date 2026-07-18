from __future__ import annotations

import pytest
import sqlite3
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils import config as app_config
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web import service


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_people_api_sync_and_list(test_memory_db_path, tmp_path, monkeypatch, client):
    # Setup temporary PEOPLE_PATH
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(app_config, "PEOPLE_PATH", people_dir)

    conn = memory.get_db_connection()
    try:
        # Create summaries with unresolved candidates
        summary_store.upsert_summary({
            "period_type": "day",
            "period_key": "2026-08-01",
            "summary": "Met Ken",
            "people": [{"name": "ケン", "note": "Ken's note"}]
        }, conn=conn)

        summary_store.upsert_summary({
            "period_type": "day",
            "period_key": "2026-08-02",
            "summary": "Met Ken again",
            "people": [{"name": "ケン", "note": "Ken's note 2"}]
        }, conn=conn)
        conn.commit()
    finally:
        conn.close()

    # 1. Get unresolved candidates list
    response = client.get("/api/v1/people/candidates")
    assert response.status_code == 200
    candidates = response.json()
    assert len(candidates) == 1
    assert candidates[0]["display_name"] == "ケン"
    cand_id = candidates[0]["candidate_id"]

    # 2. Get candidate detail
    response = client.get(f"/api/v1/people/candidates/{cand_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["candidate_id"] == cand_id
    assert len(detail["summaries"]) == 2

    # 3. Create target person note in Vault
    note_path = people_dir / "ken.md"
    note_path.write_text("""---
id: ken-suzuki
name: 鈴木健
aliases:
  - ケンちゃん
---
Suzuki Ken note.
""", encoding="utf-8")

    # Sync
    response = client.post("/api/v1/people/sync")
    assert response.status_code == 200
    sync_res = response.json()
    assert sync_res["synced"] is True

    # Check people list contains the resolved Suzuki Ken (but 'ケン' is still unresolved since 'ケン' is not linked to 'ken-suzuki' yet via UI candidate resolution)
    response = client.get("/api/v1/people")
    assert response.status_code == 200
    people = response.json()
    # Suzuki Ken is synced from Vault
    ken_person = [p for p in people if p["vault_id"] == "ken-suzuki"][0]
    assert ken_person["display_name"] == "鈴木健"
    target_person_id = ken_person["person_id"]

    # 4. Resolve 'ケン' candidate to 'Suzuki Ken'
    response = client.post(f"/api/v1/people/candidates/{cand_id}/resolve", json={"target_person_id": target_person_id})
    assert response.status_code == 200

    # Ensure alias 'ケン' is created and summaries migrated
    response = client.get(f"/api/v1/people/{target_person_id}")
    assert response.status_code == 200
    p_detail = response.json()
    assert len(p_detail["aliases"]) == 1
    assert p_detail["aliases"][0]["normalized_name"] == "ケン"
    assert len(p_detail["summaries"]) == 2  # The 2 summaries from candidate 'ケン' are migrated!


def test_people_resolve_conflicts(test_memory_db_path, tmp_path, monkeypatch, client):
    # Setup temporary PEOPLE_PATH
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(app_config, "PEOPLE_PATH", people_dir)

    conn = memory.get_db_connection()
    try:
        # Create person Suzuki Ken (vault-linked)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_ken", "鈴木健", "鈴木健", "ken-suzuki")
        )
        # Create person Sato Hanako (vault-linked)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_sato", "佐藤花子", "佐藤花子", "sato-hanako")
        )
        # Confirmed alias for Suzuki Ken
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("ケン", "peo_ken", "ケン")
        )
        # Candidate 'ケン' (which conflicts with Suzuki Ken's confirmed alias if we try to resolve it to Sato Hanako!)
        conn.execute(
            "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
            ("cand_conflict_alias", "ケン", "ケン", "unresolved")
        )
        # Candidate '鈴木健' (conflicts with main name of Suzuki Ken if we try to resolve to Sato Hanako!)
        conn.execute(
            "INSERT INTO person_candidates (candidate_id, display_name, normalized_name, status) VALUES (?, ?, ?, ?)",
            ("cand_conflict_name", "鈴木健", "鈴木健", "unresolved")
        )
        conn.commit()
    finally:
        conn.close()

    # 1. Try to resolve candidate 'ケン' to Sato Hanako (peo_sato)
    # Should reject with HTTP 409 because 'ケン' is already confirmed for Suzuki Ken (peo_ken)
    response = client.post("/api/v1/people/candidates/cand_conflict_alias/resolve", json={"target_person_id": "peo_sato"})
    assert response.status_code == 409
    err_detail = response.json()["detail"]
    assert err_detail["conflict_type"] == "alias_conflict"
    assert err_detail["existing_person_id"] == "peo_ken"

    # 2. Try to resolve candidate '鈴木健' to Sato Hanako (peo_sato)
    # Should reject with HTTP 409 because '鈴木健' matches Suzuki Ken's main normalized name
    response = client.post("/api/v1/people/candidates/cand_conflict_name/resolve", json={"target_person_id": "peo_sato"})
    assert response.status_code == 409
    err_detail = response.json()["detail"]
    assert err_detail["conflict_type"] == "main_name_conflict"
    assert err_detail["existing_person_id"] == "peo_ken"


def test_people_merge_restrictions(test_memory_db_path, client):
    conn = memory.get_db_connection()
    try:
        # Create vault-linked person A
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_a", "山田太郎", "山田太郎", "yamada-taro")
        )
        # Create vault-linked person B (different vault_id)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_b", "鈴木健", "鈴木健", "ken-suzuki")
        )
        # Create unlinked person C
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_c", "佐藤さん", "佐藤さん", None)
        )
        conn.commit()
    finally:
        conn.close()

    # 1. Merging two different Vault IDs (peo_b into peo_a) -> should fail (HTTP 400)
    response = client.post("/api/v1/people/merge", json={"from_person_id": "peo_b", "to_person_id": "peo_a"})
    assert response.status_code == 400
    assert "異なるVault ID" in response.json()["detail"]

    # 2. Merging unlinked person C into vault-linked person A -> should succeed (HTTP 200)
    response = client.post("/api/v1/people/merge", json={"from_person_id": "peo_c", "to_person_id": "peo_a"})
    assert response.status_code == 200


def test_db_vs_vault_mismatches_dynamic_report(test_memory_db_path, tmp_path, monkeypatch, client):
    # Setup temporary PEOPLE_PATH
    people_dir = tmp_path / "people"
    people_dir.mkdir()
    monkeypatch.setattr(app_config, "PEOPLE_PATH", people_dir)

    conn = memory.get_db_connection()
    try:
        # DB Confirmed alias for Suzuki Ken
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("peo_ken", "鈴木健", "鈴木健", "ken-suzuki")
        )
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("ケン", "peo_ken", "ケン")
        )
        conn.commit()
    finally:
        conn.close()

    # Note Suzuki Ken note doesn't claim 'ケン'.
    # Instead, Note Sato claims 'ケン' as alias!
    note_path = people_dir / "sato.md"
    note_path.write_text("""---
id: sato-hanako
name: 佐藤花子
aliases:
  - ケン
---
""", encoding="utf-8")

    response = client.get("/api/v1/people/vault-report")
    assert response.status_code == 200
    report = response.json()

    # Verify mismatch is reported dynamically
    db_conflicts = report["db_conflicts"]
    assert len(db_conflicts["mismatches"]) == 1
    mismatch = db_conflicts["mismatches"][0]
    assert mismatch["alias"] == "ケン"
    assert mismatch["db_person_id"] == "peo_ken"
    assert mismatch["vault_note"]["id"] == "sato-hanako"


def test_people_merge_detailed(test_memory_db_path, client):
    # This test covers all detailed merge verification and execution cases
    conn = memory.get_db_connection()
    try:
        # Create unlinked person A (山田)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("unlinked_a", "山田太郎", "山田太郎", None)
        )
        # Create vault-linked person B (鈴木, ken-suzuki)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("linked_b", "鈴木健", "鈴木健", "ken-suzuki")
        )
        # Create unlinked person C (佐藤)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("unlinked_c", "佐藤さん", "佐藤さん", None)
        )
        # Create third-party person D (田中, with conflict-inducing name/alias)
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name, vault_id) VALUES (?, ?, ?, ?)",
            ("third_d", "田中一郎", "田中一郎", "tanaka-ichiro")
        )
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("タナカ", "third_d", "タナカ")
        )

        # Aliases for source persons
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("ヤマダ", "unlinked_a", "ヤマダ")
        )

        # Summaries for both unlinked_a and linked_b
        # Create summary in DB
        conn.execute(
            "INSERT INTO summaries (summary_id, period_type, period_key, period_start, period_end, generated_at, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sum_1", "day", "2026-08-01", "2026-08-01", "2026-08-01", "2026-08-01T12:00:00+09:00", "Day 1")
        )
        # Link unlinked_a to sum_1
        conn.execute(
            "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
            ("sum_1", "unlinked_a", "山田メモ", 5)
        )
        # Link linked_b to sum_1
        conn.execute(
            "INSERT INTO summary_people (summary_id, person_id, note, display_order) VALUES (?, ?, ?, ?)",
            ("sum_1", "linked_b", "鈴木メモ", 2)
        )

        conn.commit()
    finally:
        conn.close()

    # Case 1: Preview: Unlinked -> Vault-linked (山田 -> 鈴木)
    # This should be ALLOWED!
    response = client.post("/api/v1/people/merge/preview", json={
        "from_person_id": "unlinked_a",
        "to_person_id": "linked_b"
    })
    assert response.status_code == 200
    preview = response.json()
    assert preview["allowed"] is True
    assert preview["transferred_summaries_count"] == 1
    assert preview["transferred_aliases_count"] == 2  # 'ヤマダ' + '山田太郎' (since target has neither)
    assert len(preview["merged_summaries"]) == 1
    merged_sum = preview["merged_summaries"][0]
    assert merged_sum["summary_id"] == "sum_1"
    assert "鈴木メモ\n山田メモ" in merged_sum["merged_note"]
    assert merged_sum["merged_display_order"] == 2  # min(2, 5)

    # Case 2: Preview: Vault-linked -> Unlinked (鈴木 -> 佐藤)
    # This should be REJECTED!
    response = client.post("/api/v1/people/merge/preview", json={
        "from_person_id": "linked_b",
        "to_person_id": "unlinked_c"
    })
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert "Unlinked" in response.json()["reason"] or "未連携" in response.json()["reason"]

    # Case 3: Preview: Different Vault IDs (鈴木 -> 田中)
    # This should be REJECTED!
    response = client.post("/api/v1/people/merge/preview", json={
        "from_person_id": "linked_b",
        "to_person_id": "third_d"
    })
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert "異なるVault ID" in response.json()["reason"] or "異なる" in response.json()["reason"]

    # Case 4: Preview: Third-party Name Conflict
    # Let's add an alias to unlinked_a that conflicts with Tanaka's main name (田中一郎)
    conn = memory.get_db_connection()
    try:
        conn.execute(
            "INSERT INTO person_aliases (normalized_name, person_id, display_name) VALUES (?, ?, ?)",
            ("田中一郎", "unlinked_a", "田中")
        )
        conn.commit()
    finally:
        conn.close()

    # 山田 -> 鈴木 should now be REJECTED due to Tanaka name conflict!
    response = client.post("/api/v1/people/merge/preview", json={
        "from_person_id": "unlinked_a",
        "to_person_id": "linked_b"
    })
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert "第三者" in response.json()["reason"] or "衝突" in response.json()["reason"]

    # Let's clean up that conflict-inducing alias
    conn = memory.get_db_connection()
    try:
        conn.execute("DELETE FROM person_aliases WHERE normalized_name = ?", ("田中一郎",))
        conn.commit()
    finally:
        conn.close()

    # Case 5: Preview: Third-party Alias Conflict
    # Let's temporarily change unlinked_a's main normalized name to 'タナカ' (which conflicts with third_d's alias)
    conn = memory.get_db_connection()
    try:
        conn.execute(
            "UPDATE people SET normalized_name = ? WHERE person_id = ?",
            ("タナカ", "unlinked_a")
        )
        conn.commit()
    finally:
        conn.close()

    # 山田 -> 鈴木 should now be REJECTED due to Tanaka alias conflict!
    response = client.post("/api/v1/people/merge/preview", json={
        "from_person_id": "unlinked_a",
        "to_person_id": "linked_b"
    })
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert "第三者" in response.json()["reason"] or "衝突" in response.json()["reason"]

    # Restore unlinked_a's main name
    conn = memory.get_db_connection()
    try:
        conn.execute(
            "UPDATE people SET normalized_name = ? WHERE person_id = ?",
            ("山田太郎", "unlinked_a")
        )
        conn.commit()
    finally:
        conn.close()

    # Case 6: Execute the permitted merge (山田 -> 鈴木)
    response = client.post("/api/v1/people/merge", json={
        "from_person_id": "unlinked_a",
        "to_person_id": "linked_b"
    })
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Check persistence and consistency
    conn = memory.get_db_connection()
    try:
        # unlinked_a should be deleted
        row = conn.execute("SELECT * FROM people WHERE person_id = ?", ("unlinked_a",)).fetchone()
        assert row is None

        # linked_b should remain
        row = conn.execute("SELECT * FROM people WHERE person_id = ?", ("linked_b",)).fetchone()
        assert row is not None

        # 山田太郎 & ヤマダ should be migrated as aliases to linked_b
        aliases = [r["normalized_name"] for r in conn.execute("SELECT normalized_name FROM person_aliases WHERE person_id = ?", ("linked_b",)).fetchall()]
        assert "ヤマダ" in aliases
        assert "山田太郎" in aliases

        # sum_1 should be merged for linked_b with consolidated note and display order
        link = conn.execute("SELECT * FROM summary_people WHERE summary_id = ? AND person_id = ?", ("sum_1", "linked_b")).fetchone()
        assert link is not None
        assert "鈴木メモ\n山田メモ" in link["note"]
        assert link["display_order"] == 2

        # unlinked_a's sum_1 link should be deleted
        old_link = conn.execute("SELECT * FROM summary_people WHERE summary_id = ? AND person_id = ?", ("sum_1", "unlinked_a")).fetchone()
        assert old_link is None
    finally:
        conn.close()

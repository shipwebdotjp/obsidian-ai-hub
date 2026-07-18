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

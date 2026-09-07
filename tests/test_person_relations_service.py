import pytest
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.web.services.person_relations import (
    InactiveRelationTypeError,
    InvalidDateError,
    SelfRelationError,
    compute_relation_status,
    create_person_relation_in_tx,
    get_person_relation_by_id_in_tx,
    get_person_relations_for_ai,
    add_relation_evidence,
    update_person_relation,
    update_relation_evidence,
)
from obsidian_ai_hub.web.services.people import delete_person
from obsidian_ai_hub.web.services.people_merge import (
    SelfRelationConflictError,
    merge_people,
    preview_people_merge,
)
from obsidian_ai_hub.people_sync.sync import sync_people_in_tx
from obsidian_ai_hub.agents.registry import list_available_tools


def setup_test_people(conn):
    cursor = conn.cursor()
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_1', 'alice', 'Alice')")
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_2', 'bob', 'Bob')")
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_3', 'charlie', 'Charlie')")
    conn.commit()


def test_relation_status_calculation():
    assert compute_relation_status(None, None, "2025-01-15") == "undated"
    assert compute_relation_status("2025-02-01", None, "2025-01-15") == "upcoming"
    assert compute_relation_status(None, "2025-01-01", "2025-01-15") == "ended"
    assert compute_relation_status("2025-01-01", "2025-01-31", "2025-01-15") == "active"


def test_relation_crud_and_validation(tmp_path, monkeypatch):
    db_file = tmp_path / "test_rel.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # 1. Self relation rejection
    with pytest.raises(SelfRelationError):
        create_person_relation_in_tx(
            cursor, "peo_1", "peo_1", "rlt_builtin_parent-child"
        )

    # 2. Date validation
    with pytest.raises(InvalidDateError):
        create_person_relation_in_tx(
            cursor, "peo_1", "peo_2", "rlt_builtin_parent-child", started_on="2025-02-30"
        )
    with pytest.raises(InvalidDateError):
        create_person_relation_in_tx(
            cursor, "peo_1", "peo_2", "rlt_builtin_parent-child", started_on="2025-05-01", ended_on="2025-04-01"
        )

    # 3. Inactive relation type error
    cursor.execute("UPDATE person_relation_types SET is_active = 0 WHERE relation_type_id = 'rlt_builtin_parent-child'")
    with pytest.raises(InactiveRelationTypeError):
        create_person_relation_in_tx(
            cursor, "peo_1", "peo_2", "rlt_builtin_parent-child"
        )
    cursor.execute("UPDATE person_relation_types SET is_active = 1 WHERE relation_type_id = 'rlt_builtin_parent-child'")

    # 4. Successful creation
    rel1, action = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2025-01-01",
        note="Initial note",
        initial_evidence=[{"source_type": "manual", "quote": "Quote 1"}],
    )
    assert action == "created"
    assert rel1["subject_person_id"] == "peo_1"
    assert rel1["object_person_id"] == "peo_2"
    assert len(rel1["evidence"]) == 1

    # 5. Semantic deduplication on duplicate creation
    rel2, action2 = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2025-01-01",
        note="Additional note",
        initial_evidence=[
            {"source_type": "manual", "quote": "Quote 1"}, # duplicate evidence
            {"source_type": "manual", "quote": "Quote 2"}, # new evidence
        ],
    )
    assert action2 == "merged_into_existing"
    assert rel2["relation_id"] == rel1["relation_id"]
    assert "Initial note" in rel2["note"]
    assert "Additional note" in rel2["note"]
    assert len(rel2["evidence"]) == 2

    # 6. Symmetric relation endpoint normalization
    # peo_2 > peo_1, so subject should be normalized to peo_1, object to peo_2
    rel_sym, _action_sym = create_person_relation_in_tx(
        cursor, "peo_2", "peo_1", "rlt_builtin_friend"
    )
    assert rel_sym["subject_person_id"] == "peo_1"
    assert rel_sym["object_person_id"] == "peo_2"

    conn.close()


def test_person_deletion_with_relations(tmp_path, monkeypatch):
    db_file = tmp_path / "test_del.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # peo_1 -> peo_2 (directed parent-child: subject peo_1, object peo_2)
    _rel_sub, _ = create_person_relation_in_tx(
        cursor, "peo_1", "peo_2", "rlt_builtin_parent-child", initial_evidence=[{"quote": "e1"}]
    )
    # peo_1 -> peo_3 (directed supervises: subject peo_1, object peo_3 -> wait, peo_3 -> peo_1 friend is symmetric so endpoints get normalized peo_1 < peo_3!)
    # Let's use a directed relation peo_3 -> peo_1 (reports-to) so peo_1 is object
    _rel_obj, _ = create_person_relation_in_tx(
        cursor, "peo_3", "peo_1", "rlt_builtin_reports-to", initial_evidence=[{"quote": "e2"}]
    )
    conn.commit()

    res = delete_person("peo_1")
    assert res["success"] is True
    assert res["deleted_subject_relations"] == 1
    assert res["deleted_object_relations"] == 1
    assert res["deleted_relation_evidence"] == 2

    conn2 = get_db_connection()
    c2 = conn2.cursor()
    c2.execute("SELECT COUNT(*) FROM person_relations")
    assert c2.fetchone()[0] == 0
    c2.execute("SELECT COUNT(*) FROM person_relation_evidence")
    assert c2.fetchone()[0] == 0
    conn2.close()


def test_manual_person_merge_and_self_relation_conflict(tmp_path, monkeypatch):
    db_file = tmp_path / "test_merge.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # peo_1 -> peo_2 (parent-child)
    create_person_relation_in_tx(cursor, "peo_1", "peo_2", "rlt_builtin_parent-child")
    # peo_3 -> peo_2 (parent-child)
    create_person_relation_in_tx(cursor, "peo_3", "peo_2", "rlt_builtin_parent-child")
    conn.commit()

    # 1. Merging peo_3 into peo_1 causes a duplicate (peo_1 -> peo_2 parent-child already exists)
    preview = preview_people_merge("peo_3", "peo_1")
    assert preview["allowed"] is True
    assert preview["merged_relations_count"] == 1
    assert len(preview["relation_impacts"]) == 1
    assert preview["relation_impacts"][0]["result_type"] == "merged_into_existing"

    merge_people("peo_3", "peo_1")

    # 2. Setup self-relation scenario: peo_1 -> peo_2
    # If we merge peo_2 into peo_1, peo_1 -> peo_1 would become a self-relation
    preview_self = preview_people_merge("peo_2", "peo_1")
    assert preview_self["allowed"] is False
    assert preview_self["self_relation_conflicts_count"] == 1
    assert preview_self["relation_impacts"][0]["result_type"] == "self_relation_conflict"

    with pytest.raises(SelfRelationConflictError):
        merge_people("peo_2", "peo_1")

    conn.close()


def test_vault_sync_automatic_merge_and_self_relation_skip(tmp_path, monkeypatch):
    db_file = tmp_path / "test_sync.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    cursor = conn.cursor()

    # peo_target linked to vault note "v1" with normalized_name "targetname"
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_target', 'targetname', 'Target Name', 'v1')")
    # peo_old unlinked duplicate with normalized_name "aliasname"
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_old', 'aliasname', 'Alias Name', NULL)")

    # Create relation between peo_target and peo_old
    create_person_relation_in_tx(cursor, "peo_target", "peo_old", "rlt_builtin_friend")
    conn.commit()

    notes_map = {
        "targetname": {
            "id": "v1",
            "name": "Target Name",
            "aliases": ["aliasname"],
            "file_path": "People/Target.md",
        }
    }

    # Execute sync in tx
    skipped, _ = sync_people_in_tx(conn, notes_map)
    conn.commit()

    assert len(skipped) == 1
    assert skipped[0]["from_person_id"] == "peo_old"
    assert skipped[0]["to_person_id"] == "peo_target"
    assert len(skipped[0]["skipped_relations"]) == 1

    # Verify peo_old is NOT deleted because merge was skipped
    cursor.execute("SELECT person_id FROM people WHERE person_id = 'peo_old'")
    assert cursor.fetchone() is not None
    conn.close()


def test_vault_sync_self_relation_skip_blocks_final_rename(tmp_path, monkeypatch):
    """A self-relation-conflict skip must not crash the final rename.

    peo_old keeps normalized_name 'taro'; the vault-linked target would be
    renamed to the same value, violating UNIQUE(people.normalized_name).
    Sync must record the skip, keep both rows and the relation, and skip
    only the final rename instead of raising IntegrityError.
    """
    db_file = tmp_path / "test_sync_skip_rename.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_T', 'taro_old', 'Old Name', 'v1')")
    cursor.execute("INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_O', 'taro', 'Taro', NULL)")
    create_person_relation_in_tx(cursor, "peo_O", "peo_T", "rlt_builtin_friend")
    conn.commit()

    notes_map = {
        "taro": {
            "id": "v1",
            "name": "Taro",
            "aliases": [],
            "file_path": "People/Taro.md",
        }
    }

    skipped, _ = sync_people_in_tx(conn, notes_map)
    conn.commit()

    assert len(skipped) == 1
    assert skipped[0]["from_person_id"] == "peo_O"
    assert skipped[0]["to_person_id"] == "peo_T"

    # Both rows survive; the target rename is skipped, the relation is kept.
    cursor.execute("SELECT normalized_name FROM people WHERE person_id = 'peo_T'")
    assert cursor.fetchone()[0] == "taro_old"
    cursor.execute("SELECT normalized_name FROM people WHERE person_id = 'peo_O'")
    assert cursor.fetchone()[0] == "taro"
    cursor.execute("SELECT COUNT(*) FROM person_relations")
    assert cursor.fetchone()[0] == 1
    conn.close()


def test_ai_tool_registry_non_exposure():
    # Verify that no relation tool is exposed in the public tool catalog.
    available_tools = list_available_tools()
    relation_tools = [t for t in available_tools if "relation" in t["tool_id"].lower()]
    assert len(relation_tools) == 0


def test_merge_people_rollback_on_error_leaves_no_partial_transfers(tmp_path, monkeypatch):
    db_file = tmp_path / "test_rollback.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # peo_1 -> peo_2 (parent-child)
    create_person_relation_in_tx(
        cursor, "peo_1", "peo_2", "rlt_builtin_parent-child", note="Original peo_1 rel"
    )
    # peo_3 -> peo_1 (friend) -> if we attempt to merge peo_1 into peo_3:
    # peo_1 -> peo_2 would attempt to become peo_3 -> peo_2.
    # BUT if peo_1 -> peo_1 also exists (self-relation), merging peo_1 into peo_3 would attempt peo_3 -> peo_3 which is self-relation conflict!
    # Let's create peo_3 -> peo_1 (parent-child). If we merge peo_1 into peo_3, peo_3 -> peo_1 becomes peo_3 -> peo_3 (self-relation).
    create_person_relation_in_tx(cursor, "peo_3", "peo_1", "rlt_builtin_parent-child")
    conn.commit()

    # Attempting to merge peo_1 into peo_3 must fail with SelfRelationConflictError
    with pytest.raises(SelfRelationConflictError):
        merge_people("peo_1", "peo_3")

    # Verify atomic rollback: peo_1 and peo_3 still exist, and peo_1's relations are untouched!
    conn2 = get_db_connection()
    c2 = conn2.cursor()
    c2.execute("SELECT person_id FROM people WHERE person_id IN ('peo_1', 'peo_3')")
    p_ids = {r[0] for r in c2.fetchall()}
    assert p_ids == {"peo_1", "peo_3"}

    c2.execute("SELECT subject_person_id, object_person_id FROM person_relations WHERE subject_person_id = 'peo_1'")
    rel_rows = c2.fetchall()
    assert len(rel_rows) == 1
    assert rel_rows[0][0] == "peo_1"
    assert rel_rows[0][1] == "peo_2"
    conn2.close()


def test_relation_detail_returns_relation_type_timestamps(tmp_path, monkeypatch):
    db_file = tmp_path / "test_type_ts.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    rel, action = create_person_relation_in_tx(
        cursor, "peo_1", "peo_2", "rlt_builtin_parent-child"
    )
    assert action == "created"
    conn.commit()

    cursor.execute(
        "SELECT created_at, updated_at FROM person_relation_types "
        "WHERE relation_type_id = 'rlt_builtin_parent-child'"
    )
    type_row = cursor.fetchone()

    fetched = get_person_relation_by_id_in_tx(cursor, rel["relation_id"])
    assert fetched["relation_type"]["created_at"] == type_row["created_at"]
    assert fetched["relation_type"]["updated_at"] == type_row["updated_at"]
    conn.close()


def test_update_clears_fields_with_explicit_null(tmp_path, monkeypatch):
    db_file = tmp_path / "test_clear.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    rel, _ = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2025-01-01",
        ended_on="2025-12-31",
        note="to clear",
        initial_evidence=[{"source_type": "manual", "quote": "q", "note": "n"}],
    )
    conn.commit()
    ev_id = rel["evidence"][0]["evidence_id"]

    # Explicit None with field names provided clears to NULL; omitted stays.
    updated, action = update_person_relation(
        rel["relation_id"],
        started_on=None,
        note=None,
        provided={"started_on", "note"},
    )
    assert action == "updated"
    assert updated["started_on"] is None
    assert updated["note"] is None
    assert updated["ended_on"] == "2025-12-31"

    # Legacy path without `provided` keeps previous behavior (None keeps).
    updated2, _ = update_person_relation(rel["relation_id"], note="new note")
    assert updated2["note"] == "new note"
    assert updated2["started_on"] is None
    assert updated2["ended_on"] == "2025-12-31"

    # Evidence fields follow the same rule.
    update_relation_evidence(ev_id, quote=None, provided={"quote"})
    conn2 = get_db_connection()
    c2 = conn2.cursor()
    c2.execute(
        "SELECT quote, note FROM person_relation_evidence WHERE evidence_id = ?",
        (ev_id,),
    )
    row = c2.fetchone()
    assert row["quote"] is None
    assert row["note"] == "n"
    conn2.close()
    conn.close()


def test_update_clear_with_collision_keeps_survivor_note(tmp_path, monkeypatch):
    db_file = tmp_path / "test_clear_collision.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    rel1, _ = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2025-01-01",
        note="survivor note",
    )
    rel2, _ = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2025-02-01",
        note="absorbed note",
    )
    conn.commit()

    # Moving rel2 onto rel1's period with an explicit note clear merges
    # into rel1 without resurrecting the cleared text.
    merged, action = update_person_relation(
        rel2["relation_id"],
        started_on="2025-01-01",
        note=None,
        provided={"started_on", "note"},
    )
    assert action == "merged_into_existing"
    assert merged["relation_id"] == rel1["relation_id"]
    assert merged["started_on"] == "2025-01-01"
    assert "survivor note" in (merged["note"] or "")
    assert "absorbed note" not in (merged["note"] or "")
    conn.close()


def test_empty_evidence_rejected_at_service_boundary(tmp_path, monkeypatch):
    db_file = tmp_path / "test_empty_ev.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    rel, _ = create_person_relation_in_tx(
        cursor, "peo_1", "peo_2", "rlt_builtin_parent-child"
    )
    conn.commit()

    # Direct service calls reject content-free evidence.
    with pytest.raises(ValueError):
        add_relation_evidence(rel["relation_id"])
    with pytest.raises(ValueError):
        add_relation_evidence(
            rel["relation_id"], quote="   ", note="", source_ref=None
        )
    with pytest.raises(ValueError):
        create_person_relation_in_tx(
            cursor,
            "peo_1",
            "peo_3",
            "rlt_builtin_friend",
            initial_evidence=[{"source_type": "manual"}],
        )

    # A single valid field is accepted through the same boundary.
    created = add_relation_evidence(rel["relation_id"], note="n")
    assert len(created["evidence"]) == 1
    conn.close()


def test_get_person_relations_for_ai(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ai_rel.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # Create relations involving peo_1 (Alice), peo_2 (Bob), peo_3 (Charlie)
    # 1. peo_1 -> peo_2 (directed parent-child: forward "親", reverse "子")
    rel1, _ = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2020-01-01",
        ended_on=None,
        note="Secret note 1",
        initial_evidence=[{"source_type": "manual", "quote": "Evidence 1"}],
    )

    # 2. peo_3 -> peo_1 (directed parent-child: peo_3 is parent of peo_1. From peo_1 perspective, peo_1 is object)
    rel2, _ = create_person_relation_in_tx(
        cursor,
        "peo_3",
        "peo_1",
        "rlt_builtin_parent-child",
        started_on="1990-05-10",
        ended_on="2010-05-10",
        note="Secret note 2",
        initial_evidence=[{"source_type": "manual", "quote": "Evidence 2"}],
    )

    # 3. peo_1 <-> peo_2 (symmetric friend)
    rel3, _ = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_friend",
        started_on=None,
        ended_on=None,
        note="Secret note 3",
    )
    conn.commit()

    # Fetch relations for peo_1
    ai_rels_1 = get_person_relations_for_ai("peo_1")
    assert len(ai_rels_1) == 3

    # Verify 7 fields exact match & strict non-leakage
    allowed_keys = {
        "person_id",
        "display_name",
        "relation",
        "relation_type_slug",
        "endpoint_role",
        "started_on",
        "ended_on",
    }
    forbidden_keys = [
        "relation_id",
        "relation_type_id",
        "description",
        "note",
        "status",
        "evidence",
        "created_at",
        "updated_at",
    ]

    for item in ai_rels_1:
        assert set(item.keys()) == allowed_keys
        for f_key in forbidden_keys:
            assert f_key not in item

    # Check peo_1 as subject in rel1 (peo_1 -> peo_2 parent-child)
    item_rel1 = next(r for r in ai_rels_1 if r["person_id"] == "peo_2" and r["relation_type_slug"] == "parent-child")
    assert item_rel1["display_name"] == "Bob"
    assert item_rel1["relation"] == "親である"  # forward label for parent-child
    assert item_rel1["endpoint_role"] == "subject"
    assert item_rel1["started_on"] == "2020-01-01"
    assert item_rel1["ended_on"] is None

    # Check peo_1 as object in rel2 (peo_3 -> peo_1 parent-child)
    item_rel2 = next(r for r in ai_rels_1 if r["person_id"] == "peo_3" and r["relation_type_slug"] == "parent-child")
    assert item_rel2["display_name"] == "Charlie"
    assert item_rel2["relation"] == "子である"  # reverse label for parent-child
    assert item_rel2["endpoint_role"] == "object"
    assert item_rel2["started_on"] == "1990-05-10"
    assert item_rel2["ended_on"] == "2010-05-10"

    # Fetch relations for peo_2 (Bob)
    ai_rels_2 = get_person_relations_for_ai("peo_2")
    assert len(ai_rels_2) == 2
    item_rel1_bob = next(r for r in ai_rels_2 if r["person_id"] == "peo_1" and r["relation_type_slug"] == "parent-child")
    assert item_rel1_bob["display_name"] == "Alice"
    assert item_rel1_bob["relation"] == "子である"  # reverse label from object perspective
    assert item_rel1_bob["endpoint_role"] == "object"

    # Fetch relations for non-existent person or person with no relations
    assert get_person_relations_for_ai("peo_nonexistent") == []

    conn.close()

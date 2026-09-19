import json

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
    walk_person_relations_for_ai,
    add_relation_evidence,
    update_person_relation,
    update_person_relation_in_tx,
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
    # Only the read-only relation walk tool is exposed; no relation write/edit
    # tool is registered (matches the AI non-exposure boundary for mutations).
    available_tools = list_available_tools()
    relation_tools = {
        t["tool_id"] for t in available_tools if "relation" in t["tool_id"].lower()
    }
    assert relation_tools == {"people_relations_walk"}


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


def _seed_walk_graph(tmp_path, monkeypatch):
    db_file = tmp_path / "test_walk.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name) "
        "VALUES ('peo_4', 'dave', 'Dave')"
    )
    # peo_1 -> peo_2 (active parent-child)
    create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2020-01-01",
        note="Secret walk note 1",
        initial_evidence=[{"source_type": "manual", "quote": "Secret evidence"}],
    )
    # peo_2 -> peo_3 (symmetrized friend, undated)
    create_person_relation_in_tx(
        cursor,
        "peo_2",
        "peo_3",
        "rlt_builtin_friend",
        note="Secret walk note 2",
    )
    # peo_3 -> peo_4 (ended parent-child)
    create_person_relation_in_tx(
        cursor,
        "peo_3",
        "peo_4",
        "rlt_builtin_parent-child",
        started_on="2000-01-01",
        ended_on="2010-01-01",
        note="Secret walk note 3",
    )
    conn.commit()
    return conn


def test_walk_person_relations_for_ai_graph(tmp_path, monkeypatch):
    conn = _seed_walk_graph(tmp_path, monkeypatch)
    try:
        result = walk_person_relations_for_ai("peo_1", max_hops=2)
    finally:
        conn.close()

    assert result["root"] == {"person_id": "peo_1", "display_name": "Alice"}
    assert result["max_hops"] == 2
    assert result["truncated"] is False

    hops = {n["person_id"]: n["hop"] for n in result["nodes"]}
    assert hops == {"peo_1": 0, "peo_2": 1, "peo_3": 2}

    assert len(result["edges"]) == 2
    edge_pairs = {(e["from_person_id"], e["to_person_id"]) for e in result["edges"]}
    assert edge_pairs == {("peo_1", "peo_2"), ("peo_2", "peo_3")}

    parent_edge = next(e for e in result["edges"] if e["to_person_id"] == "peo_2")
    assert parent_edge["relation"] == "親である"
    assert parent_edge["relation_type_slug"] == "parent-child"
    assert parent_edge["status"] == "active"
    assert parent_edge["started_on"] == "2020-01-01"
    assert parent_edge["ended_on"] is None

    # Node/edge fields are a fixed minimal projection; no secrets leak.
    for node in result["nodes"]:
        assert set(node.keys()) == {"person_id", "display_name", "hop"}
    for edge in result["edges"]:
        assert set(edge.keys()) == {
            "from_person_id",
            "to_person_id",
            "relation",
            "relation_type_slug",
            "status",
            "started_on",
            "ended_on",
        }
    assert "Secret" not in json.dumps(result, ensure_ascii=False)


def test_walk_person_relations_for_ai_direction_and_filters(tmp_path, monkeypatch):
    conn = _seed_walk_graph(tmp_path, monkeypatch)
    try:
        outgoing = walk_person_relations_for_ai(
            "peo_1", max_hops=3, direction="outgoing"
        )
        incoming = walk_person_relations_for_ai(
            "peo_1", max_hops=3, direction="incoming"
        )
        friend_only = walk_person_relations_for_ai(
            "peo_2", max_hops=3, relation_type_slugs=["friend"]
        )
        ended_only = walk_person_relations_for_ai(
            "peo_3", max_hops=3, statuses=["ended"]
        )
    finally:
        conn.close()

    # outgoing follows subject -> object through the chain.
    assert {n["person_id"] for n in outgoing["nodes"]} == {
        "peo_1",
        "peo_2",
        "peo_3",
        "peo_4",
    }
    # peo_1 has no incoming edges.
    assert [n["person_id"] for n in incoming["nodes"]] == ["peo_1"]
    assert incoming["edges"] == []

    assert {n["person_id"] for n in friend_only["nodes"]} == {"peo_2", "peo_3"}
    assert len(friend_only["edges"]) == 1
    assert friend_only["edges"][0]["relation_type_slug"] == "friend"

    assert {n["person_id"] for n in ended_only["nodes"]} == {"peo_3", "peo_4"}
    assert len(ended_only["edges"]) == 1
    assert ended_only["edges"][0]["status"] == "ended"


def test_walk_person_relations_for_ai_bounds_and_validation(tmp_path, monkeypatch):
    conn = _seed_walk_graph(tmp_path, monkeypatch)
    try:
        bounded = walk_person_relations_for_ai("peo_1", max_hops=2, max_nodes=2)
        deep = walk_person_relations_for_ai("peo_1", max_hops=3)
        missing = walk_person_relations_for_ai("peo_missing")
        with pytest.raises(ValueError):
            walk_person_relations_for_ai("peo_1", max_hops=4)
        with pytest.raises(ValueError):
            walk_person_relations_for_ai("peo_1", max_hops=0)
        with pytest.raises(ValueError):
            walk_person_relations_for_ai("peo_1", direction="sideways")  # type: ignore[arg-type]
    finally:
        conn.close()

    assert len(bounded["nodes"]) == 2
    assert bounded["truncated"] is True
    assert {n["person_id"] for n in deep["nodes"]} == {
        "peo_1",
        "peo_2",
        "peo_3",
        "peo_4",
    }
    assert deep["nodes"][-1]["hop"] == 3
    assert missing == {"error": "人物が見つかりません"}


def test_relation_partial_date_normalization_and_order():
    from obsidian_ai_hub.web.services.person_relations import (
        validate_and_normalize_relation_dates,
    )

    # Normalization (incl. slash variants) and empty handling
    assert validate_and_normalize_relation_dates("2023/5", None) == ("2023-05", None)
    assert validate_and_normalize_relation_dates("2023", "2024-02") == ("2023", "2024-02")
    assert validate_and_normalize_relation_dates("", "  ") == (None, None)
    assert validate_and_normalize_relation_dates(None, None) == (None, None)
    # Mixed precision compares on bounds: May 2023 .. end of 2023 is valid
    assert validate_and_normalize_relation_dates("2023-05", "2023") == ("2023-05", "2023")

    with pytest.raises(InvalidDateError):
        validate_and_normalize_relation_dates("2023-13", None)
    with pytest.raises(InvalidDateError):
        validate_and_normalize_relation_dates("2023-02-30", None)
    with pytest.raises(InvalidDateError):
        validate_and_normalize_relation_dates("not-a-date", None)
    with pytest.raises(InvalidDateError):
        # 2024-01-01 (start min) > 2023-05-31 (end max)
        validate_and_normalize_relation_dates("2024", "2023-05")


def test_relation_status_with_partial_dates():
    assert compute_relation_status("2023-05", None, "2026-09-13") == "active"
    assert compute_relation_status("2027", None, "2026-09-13") == "upcoming"
    assert compute_relation_status("2026-10", None, "2026-09-13") == "upcoming"
    assert compute_relation_status(None, "2023-05", "2026-09-13") == "ended"
    assert compute_relation_status(None, "2026-08", "2026-09-13") == "ended"
    # Bounds overlapping today count as active, not ended/upcoming
    assert compute_relation_status(None, "2026-09", "2026-09-13") == "active"
    assert compute_relation_status("2026-09", None, "2026-09-13") == "active"
    assert compute_relation_status("2026", "2026", "2026-09-13") == "active"
    # Full dates keep previous behavior
    assert compute_relation_status("2026-09-14", None, "2026-09-13") == "upcoming"
    assert compute_relation_status(None, "2026-09-12", "2026-09-13") == "ended"


def test_relation_crud_with_partial_dates(tmp_path, monkeypatch):
    db_file = tmp_path / "test_rel_partial.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    rel, action = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2023/5",
        ended_on="2024",
    )
    assert action == "created"
    assert rel["started_on"] == "2023-05"
    assert rel["ended_on"] == "2024"
    assert rel["status"] == "ended"
    cursor.execute(
        "SELECT started_on_min, ended_on_max FROM person_relations WHERE relation_id = ?",
        (rel["relation_id"],),
    )
    row = cursor.fetchone()
    assert row["started_on_min"] == "2023-05-01"
    assert row["ended_on_max"] == "2024-12-31"

    # Same period at different precision is a distinct relation (exact-match dedup)
    rel2, action2 = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2023-05-01",
    )
    assert action2 == "created"
    assert rel2["relation_id"] != rel["relation_id"]

    # Exact same normalized values still merge into existing
    rel3, action3 = create_person_relation_in_tx(
        cursor,
        "peo_1",
        "peo_2",
        "rlt_builtin_parent-child",
        started_on="2023-05",
        ended_on="2024",
        note="extra",
    )
    assert action3 == "merged_into_existing"
    assert rel3["relation_id"] == rel["relation_id"]

    # Update to year precision; explicit None clears bounds to NULL
    updated, _ = update_person_relation_in_tx(
        cursor,
        rel["relation_id"],
        started_on="2020",
        ended_on=None,
        provided={"started_on", "ended_on"},
    )
    assert updated["started_on"] == "2020"
    assert updated["ended_on"] is None
    cursor.execute(
        "SELECT started_on_min, ended_on_max FROM person_relations WHERE relation_id = ?",
        (rel["relation_id"],),
    )
    row = cursor.fetchone()
    assert row["started_on_min"] == "2020-01-01"
    assert row["ended_on_max"] is None

    conn.close()


def test_relation_ai_projection_exposes_partial_dates(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ai_partial.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()
    create_person_relation_in_tx(
        cursor, "peo_1", "peo_2", "rlt_builtin_parent-child",
        started_on="2023-05", ended_on="2024",
    )
    conn.commit()

    proj = get_person_relations_for_ai("peo_1")
    assert len(proj) == 1
    assert proj[0]["started_on"] == "2023-05"
    assert proj[0]["ended_on"] == "2024"

    conn.close()


def test_relation_person_merge_preserves_partial_dates(tmp_path, monkeypatch):
    db_file = tmp_path / "test_merge_partial.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()
    rel, _ = create_person_relation_in_tx(
        cursor, "peo_3", "peo_2", "rlt_builtin_friend",
        started_on="2023-05",
    )
    conn.commit()

    preview = preview_people_merge("peo_3", "peo_1")
    assert preview["allowed"] is True
    merge_people("peo_3", "peo_1")

    merged = get_person_relation_by_id_in_tx(conn.cursor(), rel["relation_id"])
    assert merged["subject_person_id"] == "peo_1"
    assert merged["object_person_id"] == "peo_2"
    assert merged["started_on"] == "2023-05"
    assert merged["status"] == "active"
    conn.close()


def test_migration_v43_preserves_legacy_dates_and_evidence(tmp_path, monkeypatch):
    from obsidian_ai_hub.database import run_migration_v43

    db_file = tmp_path / "test_mig43.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_test_people(conn)
    cursor = conn.cursor()

    # Simulate the pre-v43 table shape (v38 columns, no boundary columns).
    cursor.execute("PRAGMA foreign_keys = OFF;")
    cursor.execute("DROP TABLE person_relations;")
    cursor.execute("""
        CREATE TABLE person_relations (
            relation_id TEXT PRIMARY KEY,
            subject_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            object_person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
            relation_type_id TEXT NOT NULL REFERENCES person_relation_types(relation_type_id) ON DELETE RESTRICT,
            started_on TEXT,
            ended_on TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (subject_person_id != object_person_id),
            CHECK (started_on IS NULL OR ended_on IS NULL OR started_on <= ended_on)
        );
    """)
    cursor.execute(
        "INSERT INTO person_relations (relation_id, subject_person_id, object_person_id, "
        "relation_type_id, started_on, ended_on, note, created_at, updated_at) "
        "VALUES ('rel_legacy', 'peo_1', 'peo_2', 'rlt_builtin_parent-child', "
        "'2020-01-01', '2020-12-31', 'legacy', '2025-01-01T00:00:00', '2025-01-01T00:00:00')"
    )
    cursor.execute(
        "INSERT INTO person_relations (relation_id, subject_person_id, object_person_id, "
        "relation_type_id, started_on, ended_on, note, created_at, updated_at) "
        "VALUES ('rel_undated', 'peo_1', 'peo_3', 'rlt_builtin_friend', "
        "NULL, NULL, NULL, '2025-01-01T00:00:00', '2025-01-01T00:00:00')"
    )
    cursor.execute(
        "INSERT INTO person_relation_evidence (evidence_id, relation_id, source_type, quote, "
        "created_at, updated_at) VALUES ('ev_legacy', 'rel_legacy', 'manual', 'q', "
        "'2025-01-01T00:00:00', '2025-01-01T00:00:00')"
    )
    conn.commit()
    cursor.execute("PRAGMA foreign_keys = ON;")

    run_migration_v43(conn)

    cursor = conn.cursor()
    assert cursor.execute("PRAGMA user_version;").fetchone()[0] == 43
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(person_relations);")]
    assert "started_on_min" in cols
    assert "ended_on_max" in cols

    row = cursor.execute(
        "SELECT started_on, started_on_min, ended_on, ended_on_max, note "
        "FROM person_relations WHERE relation_id = 'rel_legacy'"
    ).fetchone()
    assert row["started_on"] == "2020-01-01"
    assert row["started_on_min"] == "2020-01-01"
    assert row["ended_on"] == "2020-12-31"
    assert row["ended_on_max"] == "2020-12-31"
    assert row["note"] == "legacy"

    row2 = cursor.execute(
        "SELECT started_on_min, ended_on_max FROM person_relations WHERE relation_id = 'rel_undated'"
    ).fetchone()
    assert row2["started_on_min"] is None
    assert row2["ended_on_max"] is None

    # Evidence survives the rebuild; FK enforcement is restored.
    assert cursor.execute("SELECT COUNT(*) FROM person_relation_evidence;").fetchone()[0] == 1
    assert cursor.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
    idx_names = [
        r["name"]
        for r in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='person_relations';"
        )
    ]
    assert "idx_person_relations_unique_period" in idx_names

    # New boundary CHECK rejects inverted periods at the DB level.
    with pytest.raises(Exception):
        cursor.execute(
            "INSERT INTO person_relations (relation_id, subject_person_id, object_person_id, "
            "relation_type_id, started_on, started_on_min, ended_on, ended_on_max, "
            "created_at, updated_at) VALUES ('rel_bad', 'peo_1', 'peo_2', "
            "'rlt_builtin_parent-child', '2024', '2024-01-01', '2023', '2023-12-31', "
            "'2025-01-01T00:00:00', '2025-01-01T00:00:00')"
        )

    conn.close()

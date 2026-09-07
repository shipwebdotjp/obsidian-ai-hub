import pytest
import sqlite3
from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.utils import config
from obsidian_ai_hub.utils.people_loader import load_people_notes_with_report
from obsidian_ai_hub.web.services.person_properties import (
    create_property_definition_in_tx,
    create_person_property_value_in_tx,
    list_person_properties_in_tx,
)
from obsidian_ai_hub.web.services.person_relations import create_person_relation_in_tx
from obsidian_ai_hub.people_sync.sync import sync_people_in_tx, get_db_vault_conflicts_report
from obsidian_ai_hub.web.services.people_sync import sync_people, get_vault_report_dynamic


def setup_phase2_db(conn: sqlite3.Connection):
    cursor = conn.cursor()
    # Create vault property definitions
    # 1. birth_date (vault, date, single)
    create_property_definition_in_tx(
        cursor,
        key="birth_date",
        display_name="生年月日",
        data_type="date",
        cardinality="single",
        source_type="vault",
        aliases=["birthday"],
    )
    # 2. skills (vault, select, multiple)
    create_property_definition_in_tx(
        cursor,
        key="skills",
        display_name="スキル",
        data_type="select",
        cardinality="multiple",
        source_type="vault",
        options=[
            {"option_key": "php", "display_name": "PHP"},
            {"option_key": "python", "display_name": "Python", "aliases": ["py"]},
            {"option_key": "rust", "display_name": "Rust"},
        ],
    )
    # 3. title (database, text, single)
    create_property_definition_in_tx(
        cursor,
        key="title",
        display_name="役職",
        data_type="text",
        cardinality="single",
        source_type="database",
    )
    conn.commit()


def test_vault_property_loader_and_sync_replacement(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p2.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_phase2_db(conn)
    cursor = conn.cursor()

    # Create target person peo_1 with vault_id 'v1'
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_1', 'alice', 'Alice', 'v1')"
    )
    # Create existing DB-dedicated property value for peo_1
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'title'"
    )
    def_title_id = cursor.fetchone()[0]
    create_person_property_value_in_tx(
        cursor, "peo_1", def_title_id, "Manager", is_api_call=False
    )
    conn.commit()

    # Define vault notes map with birth_date (using alias birthday) and mixed skills array
    notes_map = {
        "alice": {
            "id": "v1",
            "name": "Alice",
            "aliases": [],
            "file_path": tmp_path / "Alice.md",
            "frontmatter": {
                "id": "v1",
                "name": "Alice",
                "birthday": "1990-05-15",
                "skills": ["php", "py", {"value": "rust", "valid_from": "2026-01-01"}],
            },
        }
    }

    # Execute sync
    skipped_rels, prop_summary = sync_people_in_tx(
        conn,
        notes_map,
        {
            "invalid_properties": [],
            "parsed_properties_by_note_id": {
                "v1": {
                    # Get definition IDs from DB
                    cursor.execute(
                        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'birth_date'"
                    ).fetchone()[0]: [
                        {
                            "value_text": None,
                            "value_date": "1990-05-15",
                            "value_number": None,
                            "value_boolean": None,
                            "option_id": None,
                            "valid_from": None,
                            "valid_until": None,
                        }
                    ],
                    cursor.execute(
                        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'skills'"
                    ).fetchone()[0]: [
                        {
                            "value_text": None,
                            "value_date": None,
                            "value_number": None,
                            "value_boolean": None,
                            "option_id": cursor.execute(
                                "SELECT option_id FROM person_property_options WHERE option_key = 'php'"
                            ).fetchone()[0],
                            "valid_from": None,
                            "valid_until": None,
                        },
                        {
                            "value_text": None,
                            "value_date": None,
                            "value_number": None,
                            "value_boolean": None,
                            "option_id": cursor.execute(
                                "SELECT option_id FROM person_property_options WHERE option_key = 'python'"
                            ).fetchone()[0],
                            "valid_from": None,
                            "valid_until": None,
                        },
                        {
                            "value_text": None,
                            "value_date": None,
                            "value_number": None,
                            "value_boolean": None,
                            "option_id": cursor.execute(
                                "SELECT option_id FROM person_property_options WHERE option_key = 'rust'"
                            ).fetchone()[0],
                            "valid_from": "2026-01-01",
                            "valid_until": None,
                        },
                    ],
                }
            },
            "missing_properties_by_note_id": {"v1": []},
        },
    )
    conn.commit()

    assert prop_summary["replaced_properties_count"] == 2
    assert prop_summary["replaced_values_count"] == 4

    props = list_person_properties_in_tx(cursor, "peo_1")
    # Total properties: 1 title (database) + 1 birth_date + 3 skills = 5 values
    assert len(props) == 5

    # Check title is unchanged
    title_p = [p for p in props if p["property_key"] == "title"][0]
    assert title_p["value"] == "Manager"

    # Check birth_date
    bd_p = [p for p in props if p["property_key"] == "birth_date"][0]
    assert bd_p["value_date"] == "1990-05-15"

    # Check skills
    skill_props = [p for p in props if p["property_key"] == "skills"]
    assert len(skill_props) == 3
    keys = {p["option_key"] for p in skill_props}
    assert keys == {"php", "python", "rust"}

    conn.close()


def test_missing_property_deletion(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p2_del.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_phase2_db(conn)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_1', 'alice', 'Alice', 'v1')"
    )
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'birth_date'"
    )
    def_bd_id = cursor.fetchone()[0]

    # Create existing vault-source property value
    create_person_property_value_in_tx(
        cursor, "peo_1", def_bd_id, "1990-01-01", is_api_call=False
    )
    conn.commit()

    notes_map = {
        "alice": {
            "id": "v1",
            "name": "Alice",
            "aliases": [],
            "file_path": tmp_path / "Alice.md",
            "frontmatter": {"id": "v1", "name": "Alice"},  # birth_date is missing!
        }
    }

    _, prop_summary = sync_people_in_tx(
        conn,
        notes_map,
        {
            "invalid_properties": [],
            "parsed_properties_by_note_id": {"v1": {}},
            "missing_properties_by_note_id": {"v1": [def_bd_id]},
        },
    )
    conn.commit()

    assert prop_summary["deleted_properties_count"] == 1
    assert prop_summary["deleted_values_count"] == 1

    props = list_person_properties_in_tx(cursor, "peo_1")
    assert len(props) == 0

    conn.close()


def test_key_collision_and_invalid_property_preservation(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p2_invalid.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_phase2_db(conn)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_1', 'alice', 'Alice', 'v1')"
    )
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'birth_date'"
    )
    def_bd_id = cursor.fetchone()[0]

    # Pre-existing vault property value
    create_person_property_value_in_tx(
        cursor, "peo_1", def_bd_id, "1985-12-25", is_api_call=False
    )
    conn.commit()

    # Note with key collision: both birth_date AND birthday present in frontmatter
    fm = {
        "id": "v1",
        "name": "Alice",
        "birth_date": "1990-01-01",
        "birthday": "1990-01-02",
        "skills": ["unknown_skill"],  # Unknown option
    }

    lookup = {
        "definitions_by_id": {
            def_bd_id: {
                "property_definition_id": def_bd_id,
                "key": "birth_date",
                "display_name": "生年月日",
                "data_type": "date",
                "cardinality": "single",
                "source_type": "vault",
                "aliases": ["birthday"],
                "option_lookup": {},
            }
        },
        "key_alias_map": {"birth_date": def_bd_id, "birthday": def_bd_id},
    }

    # Test parser directly
    from obsidian_ai_hub.utils.people_loader import parse_vault_properties_for_note

    p_res = parse_vault_properties_for_note(fm, "v1", "Alice", lookup)
    assert len(p_res["invalid_properties"]) == 1
    assert "同一ノート内で複数のキー" in p_res["invalid_properties"][0]["reason"]
    # Key collision prevents birth_date from being in parsed_properties or missing_properties
    assert def_bd_id not in p_res["parsed_properties"]
    assert def_bd_id not in p_res["missing_properties"]

    # Verify that during sync, existing "1985-12-25" value is preserved
    _, prop_summary = sync_people_in_tx(
        conn,
        {"alice": {"id": "v1", "name": "Alice", "aliases": []}},
        {
            "invalid_properties": p_res["invalid_properties"],
            "parsed_properties_by_note_id": {"v1": p_res["parsed_properties"]},
            "missing_properties_by_note_id": {"v1": p_res["missing_properties"]},
        },
    )
    conn.commit()

    props = list_person_properties_in_tx(cursor, "peo_1")
    assert len(props) == 1
    assert props[0]["value_date"] == "1985-12-25"  # Untouched/preserved!

    conn.close()


def test_auto_merge_property_conflict_skipping(tmp_path, monkeypatch):
    db_file = tmp_path / "test_p2_auto_merge.db"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_file)

    conn = get_db_connection()
    setup_phase2_db(conn)
    cursor = conn.cursor()

    # Target person peo_target (vault_id='v1')
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_target', 'targetname', 'Target Name', 'v1')"
    )
    # Duplicate unlinked person peo_old (vault_id=NULL)
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name, vault_id) VALUES ('peo_old', 'aliasname', 'Alias Name', NULL)"
    )

    # Create conflicting single cardinality birth_date values for both people!
    cursor.execute(
        "SELECT property_definition_id FROM person_property_definitions WHERE key = 'birth_date'"
    )
    def_bd_id = cursor.fetchone()[0]

    create_person_property_value_in_tx(
        cursor, "peo_target", def_bd_id, "1990-01-01", is_api_call=False
    )
    create_person_property_value_in_tx(
        cursor, "peo_old", def_bd_id, "1992-02-02", is_api_call=False
    )
    conn.commit()

    notes_map = {
        "targetname": {
            "id": "v1",
            "name": "Target Name",
            "aliases": ["aliasname"],
            "file_path": tmp_path / "Target.md",
        }
    }

    # Execute sync in tx
    skipped_rels, prop_summary = sync_people_in_tx(conn, notes_map)
    conn.commit()

    # Check that auto-merge was skipped due to property conflict!
    assert len(prop_summary["skipped_property_merges"]) == 1
    spm = prop_summary["skipped_property_merges"][0]
    assert spm["from_person_id"] == "peo_old"
    assert spm["to_person_id"] == "peo_target"
    assert spm["property_key"] == "birth_date"

    # Verify both people records survive
    cursor.execute("SELECT person_id FROM people WHERE person_id = 'peo_old'")
    assert cursor.fetchone() is not None

    conn.close()

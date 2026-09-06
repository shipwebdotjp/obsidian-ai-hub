from __future__ import annotations

import sqlite3
from datetime import datetime
import pytest
from pydantic import ValidationError

from obsidian_ai_hub import memory
from obsidian_ai_hub.agents.registry import list_available_tools
from obsidian_ai_hub.database import BUILTIN_RELATION_TYPES
from obsidian_ai_hub.web.schemas import (
    PersonDeleteResponse,
    PersonDetail,
    PersonRelationCreateRequest,
    PersonRelationEvidenceCreateRequest,
    PersonRelationEvidenceUpdateRequest,
    PersonRelationTypeCreateRequest,
    PersonRelationTypeUpdateRequest,
    PersonRelationUpdateRequest,
)


def test_migration_v38_creates_tables_and_seeds_builtin_types(test_memory_db_path):
    with memory.get_db_connection() as conn:
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version == 38

        # Check tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('person_relation_types', 'person_relations', 'person_relation_evidence');"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert tables == {
            "person_relation_types",
            "person_relations",
            "person_relation_evidence",
        }

        # Check 25 builtin relation types are seeded
        cursor = conn.execute(
            "SELECT relation_type_id, slug, forward_label, reverse_label, directionality, is_builtin, is_active FROM person_relation_types WHERE is_builtin = 1;"
        )
        builtin_rows = cursor.fetchall()
        assert len(builtin_rows) == 25
        assert len(builtin_rows) == len(BUILTIN_RELATION_TYPES)

        for row in builtin_rows:
            rt_id, slug, f_label, r_label, directionality, is_builtin, is_active = row
            assert rt_id == f"rlt_builtin_{slug}"
            assert is_builtin == 1
            assert is_active == 1
            assert directionality in ("directed", "symmetric")


def test_db_unique_index_prevents_duplicate_relations_including_nulls(
    test_memory_db_path,
):
    with memory.get_db_connection() as conn:
        now = datetime.now().isoformat()
        # Seed test people
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_1', 'alice', 'Alice');"
        )
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_2', 'bob', 'Bob');"
        )

        # 1. Test duplicate relation with NULL started_on / ended_on
        conn.execute(
            """
            INSERT INTO person_relations (
                relation_id, subject_person_id, object_person_id, relation_type_id,
                started_on, ended_on, created_at, updated_at
            ) VALUES ('rel_1', 'peo_1', 'peo_2', 'rlt_builtin_friend', NULL, NULL, ?, ?);
            """,
            (now, now),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO person_relations (
                    relation_id, subject_person_id, object_person_id, relation_type_id,
                    started_on, ended_on, created_at, updated_at
                ) VALUES ('rel_2', 'peo_1', 'peo_2', 'rlt_builtin_friend', NULL, NULL, ?, ?);
                """,
                (now, now),
            )

        # 2. Test duplicate relation with dated period
        conn.execute(
            """
            INSERT INTO person_relations (
                relation_id, subject_person_id, object_person_id, relation_type_id,
                started_on, ended_on, created_at, updated_at
            ) VALUES ('rel_3', 'peo_1', 'peo_2', 'rlt_builtin_parent-child', '2020-01-01', '2023-12-31', ?, ?);
            """,
            (now, now),
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO person_relations (
                    relation_id, subject_person_id, object_person_id, relation_type_id,
                    started_on, ended_on, created_at, updated_at
                ) VALUES ('rel_4', 'peo_1', 'peo_2', 'rlt_builtin_parent-child', '2020-01-01', '2023-12-31', ?, ?);
                """,
                (now, now),
            )


def test_db_check_constraints(test_memory_db_path):
    with memory.get_db_connection() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_1', 'alice', 'Alice');"
        )

        # Self-relation CHECK constraint (subject_person_id != object_person_id)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO person_relations (
                    relation_id, subject_person_id, object_person_id, relation_type_id,
                    created_at, updated_at
                ) VALUES ('rel_self', 'peo_1', 'peo_1', 'rlt_builtin_friend', ?, ?);
                """,
                (now, now),
            )

        # Date order CHECK constraint (started_on <= ended_on)
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_2', 'bob', 'Bob');"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO person_relations (
                    relation_id, subject_person_id, object_person_id, relation_type_id,
                    started_on, ended_on, created_at, updated_at
                ) VALUES ('rel_bad_dates', 'peo_1', 'peo_2', 'rlt_builtin_friend', '2024-01-01', '2020-01-01', ?, ?);
                """,
                (now, now),
            )

        # Evidence source_type CHECK constraint (source_type = 'manual')
        conn.execute(
            """
            INSERT INTO person_relations (
                relation_id, subject_person_id, object_person_id, relation_type_id,
                created_at, updated_at
            ) VALUES ('rel_ok', 'peo_1', 'peo_2', 'rlt_builtin_friend', ?, ?);
            """,
            (now, now),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO person_relation_evidence (
                    evidence_id, relation_id, source_type, created_at, updated_at
                ) VALUES ('evi_bad', 'rel_ok', 'auto_extracted', ?, ?);
                """,
                (now, now),
            )


def test_dto_relation_type_validations():
    # Valid relation type request
    req = PersonRelationTypeCreateRequest(
        slug="business-partner",
        forward_label="ビジネスパートナーである",
        reverse_label="ビジネスパートナーである",
        directionality="symmetric",
        description="ビジネス上の協力関係",
    )
    assert req.slug == "business-partner"

    # Empty slug should be rejected
    with pytest.raises(ValidationError):
        PersonRelationTypeCreateRequest(
            slug="   ",
            forward_label="ラベル",
            reverse_label="ラベル",
            directionality="symmetric",
        )

    # Empty update label should be rejected
    with pytest.raises(ValidationError):
        PersonRelationTypeUpdateRequest(forward_label="")


def test_dto_evidence_validations():
    # Valid evidence request
    evi = PersonRelationEvidenceCreateRequest(
        source_type="manual",
        quote="2022年からの友人",
        note="手動入力",
        observed_at="2022-05-10",
    )
    assert evi.source_type == "manual"
    assert evi.observed_at == "2022-05-10"

    # Reject non-manual source_type
    with pytest.raises(ValidationError):
        PersonRelationEvidenceCreateRequest(source_type="ai_generated")

    # Reject invalid date format for observed_at
    with pytest.raises(ValidationError):
        PersonRelationEvidenceCreateRequest(observed_at="2022/05/10")

    # Update request observed_at validation
    with pytest.raises(ValidationError):
        PersonRelationEvidenceUpdateRequest(observed_at="invalid-date")


def test_dto_relation_validations():
    # Valid relation create request
    rel = PersonRelationCreateRequest(
        subject_person_id="peo_1",
        object_person_id="peo_2",
        relation_type_id="rlt_builtin_friend",
        started_on="2020-01-01",
        ended_on="2023-12-31",
    )
    assert rel.subject_person_id == "peo_1"

    # Reject invalid date order
    with pytest.raises(ValidationError):
        PersonRelationCreateRequest(
            subject_person_id="peo_1",
            object_person_id="peo_2",
            relation_type_id="rlt_builtin_friend",
            started_on="2025-01-01",
            ended_on="2020-01-01",
        )

    # Reject invalid date format
    with pytest.raises(ValidationError):
        PersonRelationUpdateRequest(started_on="2020-1-1")


def test_dto_person_delete_response_extended_fields():
    resp = PersonDeleteResponse(
        success=True,
        deleted_summary_people=1,
        deleted_aliases=2,
        deleted_assignments=3,
    )
    assert resp.deleted_subject_relations == 0
    assert resp.deleted_object_relations == 0
    assert resp.deleted_relation_evidence == 0

    resp_with_relations = PersonDeleteResponse(
        success=True,
        deleted_summary_people=1,
        deleted_aliases=2,
        deleted_assignments=3,
        deleted_subject_relations=2,
        deleted_object_relations=2,
        deleted_relation_evidence=5,
    )
    assert resp_with_relations.deleted_subject_relations == 2
    assert resp_with_relations.deleted_object_relations == 2
    assert resp_with_relations.deleted_relation_evidence == 5


def test_regression_person_detail_and_ai_registry_unchanged():
    # Verify PersonDetail does not have relation fields in Phase 1
    person_detail_fields = PersonDetail.model_fields.keys()
    assert "relations" not in person_detail_fields
    assert "person_relations" not in person_detail_fields

    # Verify AI tool registry does not have relation tools registered
    available_tools = list_available_tools()
    relation_tools = [t for t in available_tools if "relation" in t["tool_id"].lower()]
    assert len(relation_tools) == 0

import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.hitl import dispatcher
from obsidian_ai_hub.hitl import store as hitl_store
from obsidian_ai_hub.hitl.service import register_run_and_questions
from obsidian_ai_hub.summary import store as summary_store
from obsidian_ai_hub.summary.person_candidates import (
    extract_and_register_person_candidates,
    get_deterministic_run_id,
)
from obsidian_ai_hub.summary.person_candidates_handler import (
    apply_person_candidates_handler,
)
from obsidian_ai_hub.web.services import person_properties, person_relations


@pytest.fixture
def test_db():
    conn = get_db_connection()
    yield conn
    conn.close()


@pytest.fixture
def setup_people_and_schema(test_db):
    cursor = test_db.cursor()
    # Create DB property definition
    prop_def = person_properties.create_property_definition(
        key="role",
        display_name="役職",
        data_type="text",
        cardinality="single",
        source_type="database",
    )
    # Create Vault property definition (should be excluded)
    vault_def = person_properties.create_property_definition(
        key="hobbies",
        display_name="趣味",
        data_type="text",
        cardinality="multiple",
        source_type="vault",
    )

    # Create Person 1 & Person 2
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_p1', 'yamada taro', '山田太郎')"
    )
    cursor.execute(
        "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_p2', 'sato hanako', '佐藤花子')"
    )

    # Create Relation Type (builtin or active)
    cursor.execute(
        """
        INSERT OR IGNORE INTO person_relation_types (
            relation_type_id, slug, forward_label, reverse_label, directionality, is_builtin, is_active, created_at, updated_at
        ) VALUES ('rlt_test_colleague', 'test_colleague', '同僚', '同僚', 'symmetric', 0, 1, '2026-09-08T00:00:00', '2026-09-08T00:00:00')
        """
    )
    cursor.execute("SELECT relation_type_id FROM person_relation_types WHERE slug = 'test_colleague'")
    rel_type_row = cursor.fetchone()
    rel_type_id = rel_type_row[0] if rel_type_row else 'rlt_test_colleague'
    test_db.commit()

    return {
        "prop_def": prop_def,
        "vault_def": vault_def,
        "person_1": "peo_p1",
        "person_2": "peo_p2",
        "relation_type_id": rel_type_id,
    }


def test_candidate_extraction_no_confirmed_people(test_db):
    run_id = extract_and_register_person_candidates(
        summary_id="sum_test_no_people",
        date_str="2026-09-08",
        ground_truth_text="本日の日次ノート",
        resolved_people=[],
        conn=test_db,
    )
    assert run_id is None


def test_candidate_extraction_idempotency_and_existing_run(test_db, setup_people_and_schema):
    summary_id = "sum_test_idempotent"
    det_run_id = get_deterministic_run_id(summary_id)

    # Pre-insert existing run
    hitl_store.upsert_run(
        {
            "run_id": det_run_id,
            "handler": "summary.apply_person_candidates",
            "status": "completed",
            "checkpoint": "{}",
            "active_question_set_id": "set_1",
            "retry_count": 0,
            "title": "2026-09-08 日次人物変更候補",
            "display_type": "daily_person_changes",
        },
        conn=test_db,
    )

    resolved_people = [
        {"person_id": "peo_p1", "name": "山田太郎", "resolution_status": "resolved"}
    ]

    res_run_id = extract_and_register_person_candidates(
        summary_id=summary_id,
        date_str="2026-09-08",
        ground_truth_text="山田太郎さんの役職が変更された。",
        resolved_people=resolved_people,
        conn=test_db,
    )

    assert res_run_id == det_run_id
    # Run status should remain unchanged ("completed")
    run_after = hitl_store.get_run(det_run_id, conn=test_db)
    assert run_after["status"] == "completed"


def test_candidate_extraction_and_limits(test_db, setup_people_and_schema):
    summary_id = "sum_test_extraction"
    det_run_id = get_deterministic_run_id(summary_id)

    resolved_people = [
        {"person_id": "peo_p1", "name": "山田太郎", "resolution_status": "resolved"},
        {"person_id": "peo_p2", "name": "佐藤花子", "resolution_status": "resolved"},
        {"name": "未解決次郎", "resolution_status": "unresolved"}, # Should be ignored
    ]

    llm_output = {
        "property_candidates": [
            {
                "operation": "create",
                "person_id": "peo_p1",
                "property_definition_id": setup_people_and_schema["prop_def"]["property_definition_id"],
                "after": {"value": "部長", "valid_from": "2026-09-01", "note": "昇進"},
                "quote": "山田太郎さんが9月1日付けで部長に昇進した。",
                "reason": "昇進報告より",
            }
        ],
        "relation_candidates": [
            {
                "operation": "create",
                "subject_person_id": "peo_p1",
                "object_person_id": "peo_p2",
                "relation_type_id": setup_people_and_schema["relation_type_id"],
                "after": {"started_on": "2026-09-01", "note": "プロジェクトで協業"},
                "quote": "山田太郎と佐藤花子が共同プロジェクトを開始した。",
                "reason": "プロジェクト開始報告より",
            }
        ],
    }

    with patch("obsidian_ai_hub.utils.llm_client.generate_llm_response") as mock_llm:
        mock_llm.return_value = json.dumps(llm_output, ensure_ascii=False)

        run_id = extract_and_register_person_candidates(
            summary_id=summary_id,
            date_str="2026-09-08",
            ground_truth_text="要約本文",
            resolved_people=resolved_people,
            conn=test_db,
        )

    assert run_id == det_run_id

    run = hitl_store.get_run(det_run_id, conn=test_db)
    assert run is not None
    assert run["handler"] == "summary.apply_person_candidates"
    assert run["display_type"] == "daily_person_changes"
    assert run["title"] == "2026-09-08 日次人物変更候補"

    questions = hitl_store.get_questions_by_set(det_run_id, "set_1", conn=test_db)
    assert len(questions) == 2


def test_candidate_application_handler_apply_and_skip(test_db, setup_people_and_schema):
    summary_id = "sum_test_apply"
    det_run_id = get_deterministic_run_id(summary_id)
    prop_def_id = setup_people_and_schema["prop_def"]["property_definition_id"]
    rel_type_id = setup_people_and_schema["relation_type_id"]

    cand_prop = {
        "candidate_type": "property",
        "candidate_key": "cand_attr_0",
        "operation": "create",
        "summary_id": summary_id,
        "person_id": "peo_p1",
        "property_definition_id": prop_def_id,
        "after": {"value": "課長", "valid_from": "2026-09-01", "note": None},
        "quote": "山田太郎が課長に就任。",
        "reason": "人事発令より",
    }

    cand_rel = {
        "candidate_type": "relation",
        "candidate_key": "cand_rel_0",
        "operation": "create",
        "summary_id": summary_id,
        "subject_person_id": "peo_p1",
        "object_person_id": "peo_p2",
        "relation_type_id": rel_type_id,
        "after": {"started_on": "2026-09-01", "note": None},
        "quote": "山田と佐藤が同僚になった。",
        "reason": "同僚報告より",
    }

    questions_data = [
        {
            "question_key": "cand_attr_0",
            "question_type": "select",
            "display_text": "属性作成",
            "choices": [{"value": "apply", "label": "適用"}, {"value": "skip", "label": "見送り"}],
            "context_json": cand_prop,
        },
        {
            "question_key": "cand_rel_0",
            "question_type": "select",
            "display_text": "関係作成",
            "choices": [{"value": "apply", "label": "適用"}, {"value": "skip", "label": "見送り"}],
            "context_json": cand_rel,
        },
    ]

    register_run_and_questions(
        run_id=det_run_id,
        handler="summary.apply_person_candidates",
        checkpoint="{}",
        question_set_id="set_1",
        questions_data=questions_data,
        conn=test_db,
        title="2026-09-08 日次人物変更候補",
        display_type="daily_person_changes",
    )
    # Set question status to answered
    for q in questions_data:
        q_obj = hitl_store.get_question(det_run_id, "set_1", q["question_key"], conn=test_db)
        hitl_store.update_question_status_and_answer(
            q_obj["question_id"], status="answered", answer={"value": "apply"}, conn=test_db
        )

    ctx = dispatcher.HitlContext(
        run_id=det_run_id,
        checkpoint="{}",
        answers_by_question_key={"cand_attr_0": "apply", "cand_rel_0": "apply"},
        conn=test_db,
    )

    result = apply_person_candidates_handler(ctx)
    assert result.status == "completed"

    # Verify Property created in DB
    props = person_properties.list_person_properties("peo_p1")
    assert len(props) == 1
    assert props[0]["value"] == "課長"

    # Verify Relation created in DB with Evidence
    rels = person_relations.list_person_relations_for_person("peo_p1")
    assert len(rels) == 1
    rel = rels[0]
    assert rel["relation_type_id"] == rel_type_id
    assert len(rel["evidence"]) == 1
    assert rel["evidence"][0]["source_ref"] == f"summary:{summary_id}"
    assert rel["evidence"][0]["quote"] == "山田と佐藤が同僚になった。"


def test_candidate_application_handler_skip_on_conflict(test_db, setup_people_and_schema):
    summary_id = "sum_test_conflict"
    det_run_id = get_deterministic_run_id(summary_id)
    prop_def_id = setup_people_and_schema["prop_def"]["property_definition_id"]

    # Candidate attempting to update property value peo_nonexistent
    cand_invalid = {
        "candidate_type": "property",
        "candidate_key": "cand_attr_invalid",
        "operation": "update",
        "summary_id": summary_id,
        "person_id": "peo_nonexistent",
        "property_definition_id": prop_def_id,
        "property_value_id": "propval_nonexistent",
        "after": {"value": "課長"},
        "quote": "",
        "reason": "",
    }

    register_run_and_questions(
        run_id=det_run_id,
        handler="summary.apply_person_candidates",
        checkpoint="{}",
        question_set_id="set_1",
        questions_data=[
            {
                "question_key": "cand_attr_invalid",
                "question_type": "select",
                "display_text": "無効候補",
                "choices": [{"value": "apply", "label": "適用"}],
                "context_json": cand_invalid,
            }
        ],
        conn=test_db,
        title="2026-09-08 日次人物変更候補",
        display_type="daily_person_changes",
    )

    q_obj = hitl_store.get_question(det_run_id, "set_1", "cand_attr_invalid", conn=test_db)
    hitl_store.update_question_status_and_answer(
        q_obj["question_id"], status="answered", answer={"value": "apply"}, conn=test_db
    )

    ctx = dispatcher.HitlContext(
        run_id=det_run_id,
        checkpoint="{}",
        answers_by_question_key={"cand_attr_invalid": "apply"},
        conn=test_db,
    )

    result = apply_person_candidates_handler(ctx)
    assert result.status == "completed"

    cp = json.loads(result.checkpoint)
    assert "cand_attr_invalid" in cp["skipped_candidate_keys"]
    assert "cand_attr_invalid" not in cp["applied_candidate_keys"]

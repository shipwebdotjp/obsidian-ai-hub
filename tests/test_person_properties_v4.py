import json
from unittest.mock import patch
import pytest

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.agents.registry import people_get
from obsidian_ai_hub.web.services.person_properties import (
    create_property_definition,
    create_person_property_value,
    get_person_properties_for_ai,
)


@pytest.fixture
def test_db_setup(test_memory_db_path):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Insert sample person
    cursor.execute(
        """
        INSERT INTO people (person_id, display_name, normalized_name, vault_id)
        VALUES ('peo_sample', '山田 太郎', '山田太郎', 'vault_p1')
        """
    )
    cursor.execute(
        """
        INSERT INTO people (person_id, display_name, normalized_name, vault_id)
        VALUES ('peo_empty', '佐藤 花子', '佐藤花子', NULL)
        """
    )
    conn.commit()
    conn.close()

    return test_memory_db_path


def test_get_person_properties_for_ai(test_db_setup):
    # Setup property definitions
    def_skill = create_property_definition(
        key="skill",
        display_name="スキル",
        data_type="text",
        cardinality="multiple",
        source_type="database",
    )
    def_gender = create_property_definition(
        key="gender",
        display_name="性別",
        data_type="select",
        cardinality="single",
        source_type="database",
        options=[
            {"option_key": "male", "display_name": "男性"},
            {"option_key": "female", "display_name": "女性"},
        ],
    )
    def_birth = create_property_definition(
        key="birthdate",
        display_name="生年月日",
        data_type="date",
        cardinality="single",
        source_type="vault",
    )
    def_active = create_property_definition(
        key="active",
        display_name="アクティブ",
        data_type="boolean",
        cardinality="single",
        source_type="database",
    )
    def_score = create_property_definition(
        key="score",
        display_name="スコア",
        data_type="number",
        cardinality="single",
        source_type="database",
    )

    # Insert values for peo_sample
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_skill["property_definition_id"],
        value="Python",
        valid_from="2020-01-01",
        note="社内メモ（AI非公開）",
    )
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_skill["property_definition_id"],
        value="Rust",
        valid_from="2023-01-01",
        note="学習中",
    )
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_gender["property_definition_id"],
        value="male",
    )
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_active["property_definition_id"],
        value=True,
    )
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_score["property_definition_id"],
        value=95.5,
    )

    # Vault property value inserted bypassing API check (simulating sync)
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO person_property_values (
                property_value_id, person_id, property_definition_id, source_type,
                value_date, valid_from, note, created_at, updated_at
            ) VALUES ('pv_birth', 'peo_sample', ?, 'vault', '1990-05-15', '1990-05-15', 'secret note', '2026-01-01T00:00:00+09:00', '2026-01-01T00:00:00+09:00')
            """,
            (def_birth["property_definition_id"],),
        )
    conn.close()

    props = get_person_properties_for_ai("peo_sample")

    # Order check: key ASC ('active', 'birthdate', 'gender', 'score', 'skill', 'skill')
    keys = [p["key"] for p in props]
    assert keys == ["active", "birthdate", "gender", "score", "skill", "skill"]

    # Verify exact structure
    expected_fields = {"key", "display_name", "data_type", "value", "valid_from", "valid_until"}
    for p in props:
        assert set(p.keys()) == expected_fields
        # Ensure internal metadata is NOT in keys
        assert "property_value_id" not in p
        assert "property_definition_id" not in p
        assert "source_type" not in p
        assert "note" not in p
        assert "created_at" not in p

    # Specific value checks
    active_prop = next(p for p in props if p["key"] == "active")
    assert active_prop == {
        "key": "active",
        "display_name": "アクティブ",
        "data_type": "boolean",
        "value": True,
        "valid_from": None,
        "valid_until": None,
    }

    birth_prop = next(p for p in props if p["key"] == "birthdate")
    assert birth_prop == {
        "key": "birthdate",
        "display_name": "生年月日",
        "data_type": "date",
        "value": "1990-05-15",
        "valid_from": "1990-05-15",
        "valid_until": None,
    }

    gender_prop = next(p for p in props if p["key"] == "gender")
    assert gender_prop == {
        "key": "gender",
        "display_name": "性別",
        "data_type": "select",
        "value": "male",  # canonical option_key
        "valid_from": None,
        "valid_until": None,
    }

    score_prop = next(p for p in props if p["key"] == "score")
    assert score_prop == {
        "key": "score",
        "display_name": "スコア",
        "data_type": "number",
        "value": 95.5,
        "valid_from": None,
        "valid_until": None,
    }

    skills = [p for p in props if p["key"] == "skill"]
    assert len(skills) == 2
    assert skills[0]["value"] == "Python"
    assert skills[1]["value"] == "Rust"


def test_get_person_properties_for_ai_empty(test_db_setup):
    props = get_person_properties_for_ai("peo_empty")
    assert props == []

    props_nonexistent = get_person_properties_for_ai("peo_nonexistent")
    assert props_nonexistent == []


def test_people_get_tool_with_properties(test_db_setup):
    def_skill = create_property_definition(
        key="skill",
        display_name="スキル",
        data_type="text",
        cardinality="multiple",
    )
    create_person_property_value(
        person_id="peo_sample",
        property_definition_id=def_skill["property_definition_id"],
        value="Python",
    )

    # Mock vault note resolution to return None (vault note missing)
    with patch("obsidian_ai_hub.agents.registry._resolve_person_vault_note", return_value=None):
        raw_res = people_get.invoke({"person_id": "peo_sample"})
        res = json.loads(raw_res)

        assert res["person_id"] == "peo_sample"
        assert "properties" in res
        assert len(res["properties"]) == 1
        assert res["properties"][0] == {
            "key": "skill",
            "display_name": "スキル",
            "data_type": "text",
            "value": "Python",
            "valid_from": None,
            "valid_until": None,
        }


def test_people_get_tool_empty_properties(test_db_setup):
    raw_res = people_get.invoke({"person_id": "peo_empty"})
    res = json.loads(raw_res)

    assert res["person_id"] == "peo_empty"
    assert "properties" in res
    assert res["properties"] == []


def test_people_get_tool_not_found(test_db_setup):
    raw_res = people_get.invoke({"person_id": "peo_nonexistent"})
    res = json.loads(raw_res)

    assert res == {"error": "人物が見つかりません"}

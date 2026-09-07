from __future__ import annotations

import sqlite3
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.agents.registry import list_available_tools
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.schemas import PersonDetail
from obsidian_ai_hub.web.services import person_properties as prop_service
from obsidian_ai_hub.web.services import people as people_service
from obsidian_ai_hub.web.services import people_merge as merge_service


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


@pytest.fixture
def seed_test_person(test_memory_db_path):
    with memory.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_test1', 'alice', 'Alice');"
        )
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_test2', 'bob', 'Bob');"
        )
        conn.commit()
    return "peo_test1", "peo_test2"


def test_migration_v39_creates_tables(test_memory_db_path):
    with memory.get_db_connection() as conn:
        version = conn.execute("PRAGMA user_version;").fetchone()[0]
        assert version >= 39

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ("
            "'person_property_definitions', 'person_property_definition_aliases', "
            "'person_property_options', 'person_property_option_aliases', 'person_property_values');"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert tables == {
            "person_property_definitions",
            "person_property_definition_aliases",
            "person_property_options",
            "person_property_option_aliases",
            "person_property_values",
        }


def test_property_definition_crud(test_memory_db_path):
    # 1. Create text definition
    def_text = prop_service.create_property_definition(
        key="skills",
        display_name="スキル",
        data_type="text",
        cardinality="multiple",
        source_type="database",
        aliases=["skill_set"],
    )
    assert def_text["key"] == "skills"
    assert def_text["display_name"] == "スキル"
    assert def_text["aliases"] == ["skill_set"]

    # 2. Create select definition with options and option aliases
    def_select = prop_service.create_property_definition(
        key="gender",
        display_name="性別",
        data_type="select",
        cardinality="single",
        source_type="database",
        options=[
          {"option_key": "male", "display_name": "男性", "display_order": 0, "aliases": ["man", "男"]},
          {"option_key": "female", "display_name": "女性", "display_order": 1, "aliases": ["woman", "女"]},
        ],
    )
    assert def_select["data_type"] == "select"
    assert len(def_select["options"]) == 2
    assert def_select["options"][0]["aliases"] == ["man", "男"]

    # 3. Update definition (display_name & aliases)
    updated = prop_service.update_property_definition(
        def_text["property_definition_id"],
        display_name="特技・スキル",
        aliases=["skill_set", "abilities"],
    )
    assert updated["display_name"] == "特技・スキル"
    assert updated["aliases"] == ["abilities", "skill_set"]

    # 4. List definitions
    all_defs = prop_service.list_property_definitions()
    assert len(all_defs) >= 2

    # 5. Delete definition
    del_res = prop_service.delete_property_definition(def_text["property_definition_id"])
    assert del_res["success"] is True
    assert del_res["deleted_property_definition_id"] == def_text["property_definition_id"]


def test_key_conflict_rejection(test_memory_db_path):
    prop_service.create_property_definition(
        key="birth_date",
        display_name="生年月日",
        data_type="date",
        cardinality="single",
        source_type="database",
    )

    with pytest.raises(prop_service.KeyConflictError):
        prop_service.create_property_definition(
            key="birth_date",
            display_name="誕生日",
            data_type="date",
            cardinality="single",
            source_type="database",
        )


def test_property_values_typed_crud_and_period_overlap(seed_test_person):
    p1_id, p2_id = seed_test_person

    # Create definitions
    d_single = prop_service.create_property_definition(
        key="job_title",
        display_name="役職",
        data_type="text",
        cardinality="single",
        source_type="database",
    )

    d_select = prop_service.create_property_definition(
        key="department",
        display_name="部署",
        data_type="select",
        cardinality="multiple",
        source_type="database",
        options=[
            {"option_key": "dev", "display_name": "開発部", "display_order": 0, "aliases": ["engineering"]},
            {"option_key": "sales", "display_name": "営業部", "display_order": 1, "aliases": ["commercial"]},
        ],
    )

    # 1. Create value with period
    val1 = prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_single["property_definition_id"],
        value="マネージャー",
        valid_from="2020-01-01",
        valid_until="2022-12-31",
        note="初期役職",
    )
    assert val1["value"] == "マネージャー"
    assert val1["valid_from"] == "2020-01-01"

    # 2. Reject period overlap for single-cardinality property
    with pytest.raises(prop_service.SingleCardinalityOverlapError):
        prop_service.create_person_property_value(
            person_id=p1_id,
            property_definition_id=d_single["property_definition_id"],
            value="ディレクター",
            valid_from="2022-01-01", # Overlaps with 2020-01-01 ~ 2022-12-31
            valid_until="2025-12-31",
        )

    # Non-overlapping period is accepted
    val2 = prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_single["property_definition_id"],
        value="部長",
        valid_from="2023-01-01",
        valid_until=None,
    )
    assert val2["value"] == "部長"

    # 3. Option alias resolution for select data type
    val_select = prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_select["property_definition_id"],
        value="engineering", # Option alias
    )
    assert val_select["option_key"] == "dev"
    assert val_select["option_display_name"] == "開発部"

    # 4. List person properties
    props = prop_service.list_person_properties(p1_id)
    assert len(props) == 3

    # 5. Delete property value
    del_val_res = prop_service.delete_person_property_value(val1["property_value_id"])
    assert del_val_res["success"] is True


def test_vault_source_property_readonly_enforcement(seed_test_person):
    p1_id, _ = seed_test_person

    d_vault = prop_service.create_property_definition(
        key="vault_note_type",
        display_name="ノート種別",
        data_type="text",
        cardinality="single",
        source_type="vault",
    )

    # API call to write vault source property must be rejected
    with pytest.raises(prop_service.VaultSourceReadOnlyError):
        prop_service.create_person_property_value(
            person_id=p1_id,
            property_definition_id=d_vault["property_definition_id"],
            value="Vault Note Value",
        )


def test_option_in_use_rejection(seed_test_person):
    p1_id, _ = seed_test_person

    d_sel = prop_service.create_property_definition(
        key="status",
        display_name="ステータス",
        data_type="select",
        cardinality="single",
        source_type="database",
        options=[
            {"option_key": "active", "display_name": "有効"},
            {"option_key": "inactive", "display_name": "無効"},
        ],
    )

    prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_sel["property_definition_id"],
        value="active",
    )

    # Updating definition by removing in-use option 'active' must be rejected
    with pytest.raises(prop_service.OptionInUseError):
        prop_service.update_property_definition(
            d_sel["property_definition_id"],
            options=[{"option_key": "inactive", "display_name": "無効"}],
        )


def test_person_deletion_cleans_up_properties(seed_test_person):
    p1_id, _ = seed_test_person

    d_text = prop_service.create_property_definition(
        key="motto",
        display_name="座右の銘",
        data_type="text",
        cardinality="multiple",
        source_type="database",
    )

    prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_text["property_definition_id"],
        value="初志貫徹",
    )

    del_res = people_service.delete_person(p1_id)
    assert del_res["success"] is True
    assert del_res["deleted_property_values"] == 1


def test_person_merge_property_preview_and_transfer(seed_test_person):
    p1_id, p2_id = seed_test_person

    d_sing = prop_service.create_property_definition(
        key="location",
        display_name="居住地",
        data_type="text",
        cardinality="single",
        source_type="database",
    )

    # Set non-overlapping values
    prop_service.create_person_property_value(
        person_id=p1_id,
        property_definition_id=d_sing["property_definition_id"],
        value="東京",
        valid_from="2020-01-01",
        valid_until="2022-12-31",
    )

    prop_service.create_person_property_value(
        person_id=p2_id,
        property_definition_id=d_sing["property_definition_id"],
        value="大阪",
        valid_from="2023-01-01",
        valid_until="2025-12-31",
    )

    preview = merge_service.preview_people_merge(p1_id, p2_id)
    assert preview["allowed"] is True
    assert preview["transferred_properties_count"] == 1
    assert preview["property_conflicts_count"] == 0

    # Merge execution transfers property
    merged = merge_service.merge_people(p1_id, p2_id)
    assert merged is True

    p2_props = prop_service.list_person_properties(p2_id)
    assert len(p2_props) == 2


def test_api_person_property_definitions_and_values_routes(client, test_memory_db_path):
    # 1. Create property definition via API
    create_def_resp = client.post(
        "/api/v1/person-property-definitions",
        json={
            "key": "certifications",
            "display_name": "資格",
            "data_type": "text",
            "cardinality": "multiple",
            "source_type": "database",
            "aliases": ["certs"],
        },
    )
    assert create_def_resp.status_code == 201
    def_data = create_def_resp.json()
    def_id = def_data["property_definition_id"]

    # 2. Get property definitions
    list_def_resp = client.get("/api/v1/person-property-definitions")
    assert list_def_resp.status_code == 200
    assert len(list_def_resp.json()) >= 1

    # Seed person
    with memory.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_api1', 'charlie', 'Charlie');"
        )
        conn.commit()

    # 3. Create person property value via API
    create_val_resp = client.post(
        "/api/v1/people/peo_api1/properties",
        json={
            "property_definition_id": def_id,
            "value": "AWS Certified Solutions Architect",
            "valid_from": "2021-06-01",
        },
    )
    assert create_val_resp.status_code == 201
    val_data = create_val_resp.json()
    val_id = val_data["property_value_id"]

    # 4. Get person properties via API
    get_props_resp = client.get("/api/v1/people/peo_api1/properties")
    assert get_props_resp.status_code == 200
    assert len(get_props_resp.json()) == 1

    # 5. Delete person property value via API
    del_val_resp = client.delete(f"/api/v1/people/peo_api1/properties/{val_id}")
    assert del_val_resp.status_code == 200
    assert del_val_resp.json()["success"] is True


def test_regression_person_detail_and_ai_registry_unchanged():
    # Verify PersonDetail does not include properties in output format in Phase 1
    person_detail_fields = PersonDetail.model_fields.keys()
    assert "properties" not in person_detail_fields
    assert "person_properties" not in person_detail_fields

    # Verify AI tool registry does not have property tools registered
    available_tools = list_available_tools()
    prop_tools = [t for t in available_tools if "property" in t["tool_id"].lower() or "properties" in t["tool_id"].lower()]
    assert len(prop_tools) == 0

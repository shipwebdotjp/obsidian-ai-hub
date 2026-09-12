from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.services import person_properties as prop_service


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


@pytest.fixture
def seed_people(test_memory_db_path):
    with memory.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_b1', 'bulk1', 'Bulk1');"
        )
        conn.execute(
            "INSERT INTO people (person_id, normalized_name, display_name) VALUES ('peo_b2', 'bulk2', 'Bulk2');"
        )
        conn.commit()
    return "peo_b1", "peo_b2"


@pytest.fixture
def multi_def(test_memory_db_path):
    return prop_service.create_property_definition(
        key="bulk_skill",
        display_name="スキル",
        data_type="text",
        cardinality="multiple",
        source_type="database",
    )


def test_bulk_add_update_delete(seed_people, multi_def):
    p1, _ = seed_people
    def_id = multi_def["property_definition_id"]

    # Add two values at once
    saved = prop_service.replace_person_property_values(
        person_id=p1,
        property_definition_id=def_id,
        items=[{"value": "php"}, {"value": "python", "note": "得意"}],
    )
    assert len(saved) == 2
    id_php = next(v["property_value_id"] for v in saved if v["value"] == "php")
    id_py = next(v["property_value_id"] for v in saved if v["value"] == "python")

    # Update one, drop one, add one
    saved2 = prop_service.replace_person_property_values(
        person_id=p1,
        property_definition_id=def_id,
        items=[
            {"property_value_id": id_py, "value": "python3", "note": "更新"},
            {"value": "rust"},
        ],
    )
    values = sorted(v["value"] for v in saved2)
    assert values == ["python3", "rust"]
    ids = {v["property_value_id"] for v in saved2}
    assert id_py in ids
    assert id_php not in ids

    # Empty list deletes all
    saved3 = prop_service.replace_person_property_values(
        person_id=p1, property_definition_id=def_id, items=[]
    )
    assert saved3 == []
    assert prop_service.list_person_properties(p1) == []


def test_bulk_type_error_rolls_back_all(seed_people, multi_def):
    p1, _ = seed_people
    def_id = multi_def["property_definition_id"]
    before = prop_service.replace_person_property_values(
        person_id=p1, property_definition_id=def_id, items=[{"value": "go"}]
    )
    assert len(before) == 1

    num_def = prop_service.create_property_definition(
        key="bulk_num",
        display_name="数値",
        data_type="number",
        cardinality="multiple",
        source_type="database",
    )
    with pytest.raises(prop_service.InvalidValueError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=num_def["property_definition_id"],
            items=[{"value": "ok-but-not"}, {"value": "not-a-number"}],
        )
    # Number def has no values; text def untouched
    assert prop_service.list_person_properties(p1) == before

    with pytest.raises(prop_service.InvalidValueError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=def_id,
            items=[
                {"property_value_id": before[0]["property_value_id"], "value": "go2"},
                {"value": ""},  # empty text is invalid -> whole tx must roll back
            ],
        )
    assert prop_service.list_person_properties(p1) == before


def test_bulk_rejects_foreign_value_ids(seed_people, multi_def):
    p1, p2 = seed_people
    def_id = multi_def["property_definition_id"]

    other_def = prop_service.create_property_definition(
        key="bulk_other",
        display_name="別属性",
        data_type="text",
        cardinality="multiple",
        source_type="database",
    )
    foreign_person = prop_service.create_person_property_value(
        person_id=p2, property_definition_id=def_id, value="bob-skill"
    )
    foreign_def = prop_service.create_person_property_value(
        person_id=p1,
        property_definition_id=other_def["property_definition_id"],
        value="other-val",
    )

    with pytest.raises(ValueError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=def_id,
            items=[{"property_value_id": foreign_person["property_value_id"], "value": "x"}],
        )
    with pytest.raises(ValueError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=def_id,
            items=[{"property_value_id": foreign_def["property_value_id"], "value": "x"}],
        )
    with pytest.raises(FileNotFoundError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=def_id,
            items=[{"property_value_id": "propval_missing", "value": "x"}],
        )


def test_bulk_rejects_single_and_vault(seed_people):
    p1, _ = seed_people
    single_def = prop_service.create_property_definition(
        key="bulk_single",
        display_name="単数",
        data_type="text",
        cardinality="single",
        source_type="database",
    )
    with pytest.raises(ValueError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=single_def["property_definition_id"],
            items=[{"value": "a"}],
        )

    vault_def = prop_service.create_property_definition(
        key="bulk_vault",
        display_name="Vault",
        data_type="text",
        cardinality="multiple",
        source_type="vault",
    )
    with pytest.raises(prop_service.VaultSourceReadOnlyError):
        prop_service.replace_person_property_values(
            person_id=p1,
            property_definition_id=vault_def["property_definition_id"],
            items=[{"value": "a"}],
        )


def test_bulk_api_and_legacy_crud_compat(client, test_memory_db_path, seed_people, multi_def):
    p1, _ = seed_people
    def_id = multi_def["property_definition_id"]

    # Legacy single-create still works on a multiple attribute
    legacy = client.post(
        f"/api/v1/people/{p1}/properties",
        json={"property_definition_id": def_id, "value": "legacy-one"},
    )
    assert legacy.status_code == 201
    legacy_id = legacy.json()["property_value_id"]

    # Bulk API replaces the full set
    bulk = client.put(
        f"/api/v1/people/{p1}/properties/by-definition/{def_id}",
        json={"values": [{"property_value_id": legacy_id, "value": "legacy-two"}, {"value": "bulk-new"}]},
    )
    assert bulk.status_code == 200
    assert sorted(v["value"] for v in bulk.json()) == ["bulk-new", "legacy-two"]

    # Legacy single update/delete still work afterwards
    kept_id = next(v["property_value_id"] for v in bulk.json() if v["value"] == "bulk-new")
    upd = client.patch(
        f"/api/v1/people/{p1}/properties/{kept_id}", json={"value": "bulk-renamed"}
    )
    assert upd.status_code == 200
    assert upd.json()["value"] == "bulk-renamed"

    # Bulk rejects single and vault definitions via API
    single_def = prop_service.create_property_definition(
        key="bulk_api_single",
        display_name="単数",
        data_type="text",
        cardinality="single",
        source_type="database",
    )
    bad_single = client.put(
        f"/api/v1/people/{p1}/properties/by-definition/{single_def['property_definition_id']}",
        json={"values": [{"value": "x"}]},
    )
    assert bad_single.status_code == 400

    vault_def = prop_service.create_property_definition(
        key="bulk_api_vault",
        display_name="Vault",
        data_type="text",
        cardinality="multiple",
        source_type="vault",
    )
    bad_vault = client.put(
        f"/api/v1/people/{p1}/properties/by-definition/{vault_def['property_definition_id']}",
        json={"values": [{"value": "x"}]},
    )
    assert bad_vault.status_code == 409

    # Foreign value id is rejected
    bad_foreign = client.put(
        f"/api/v1/people/{p1}/properties/by-definition/{def_id}",
        json={"values": [{"property_value_id": "propval_missing", "value": "x"}]},
    )
    assert bad_foreign.status_code == 404

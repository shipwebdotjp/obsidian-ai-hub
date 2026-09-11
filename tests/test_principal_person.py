import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.service import (
    delete_person,
    get_principal_person,
    merge_people,
    set_principal_person,
    unset_principal_person,
    PrincipalPersonConflictError,
)
from obsidian_ai_hub.summary.store import normalize_entity_name


def _helper_create_person(display_name: str) -> dict:
    conn = get_db_connection()
    import uuid
    p_id = f"peo_{uuid.uuid4().hex[:8]}"
    norm = normalize_entity_name(display_name)
    with conn:
        conn.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            (p_id, display_name, norm),
        )
    return {"person_id": p_id, "display_name": display_name, "normalized_name": norm}


from obsidian_ai_hub.web.services.person_relations import (
    create_person_relation,
    create_person_relation_type,
    get_relationship_to_principal_for_ai,
)
from obsidian_ai_hub.agents.registry import resolve_tools_with_context


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_principal_person_service_crud():
    # 1. Initially unset
    unset_principal_person()
    res = get_principal_person()
    assert res == {"principal_person_id": None, "display_name": None}

    # 2. Create person and set as principal
    p1 = _helper_create_person("Peo 1")
    p1_id = p1["person_id"]

    set_res = set_principal_person(p1_id)
    assert set_res["principal_person_id"] == p1_id
    assert set_res["display_name"] == "Peo 1"

    get_res = get_principal_person()
    assert get_res["principal_person_id"] == p1_id
    assert get_res["display_name"] == "Peo 1"

    # 3. Try to set non-existent person -> FileNotFoundError
    with pytest.raises(FileNotFoundError):
        set_principal_person("peo_nonexistent")

    # 4. Unset principal
    unset_principal_person()
    assert get_principal_person() == {"principal_person_id": None, "display_name": None}


def test_principal_person_deletion_block_and_merge_transfer():
    unset_principal_person()
    p1 = _helper_create_person("Principal One")
    p2 = _helper_create_person("Target Two")
    p1_id = p1["person_id"]
    p2_id = p2["person_id"]

    set_principal_person(p1_id)

    # Deleting p1 should raise PrincipalPersonConflictError
    with pytest.raises(PrincipalPersonConflictError):
        delete_person(p1_id)

    # Merging p1 into p2 should update principal_person_settings to p2_id in same transaction
    merge_people(from_person_id=p1_id, to_person_id=p2_id)
    get_res = get_principal_person()
    assert get_res["principal_person_id"] == p2_id
    assert get_res["display_name"] == "Target Two"

    # Cleanup
    unset_principal_person()
    delete_person(p2_id)


def test_principal_person_api_endpoints(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    client = TestClient(app)

    # 1. Unauthenticated request -> 401
    res = client.get("/api/v1/people/principal")
    assert res.status_code == 401

    # 2. GET initially unset -> 200 with nulls
    res = client.get("/api/v1/people/principal", headers=api_auth_headers)
    assert res.status_code == 200
    assert res.json() == {"principal_person_id": None, "display_name": None}

    # 3. Create person via service, set via PUT /people/principal
    p = _helper_create_person("API Principal User")
    p_id = p["person_id"]

    put_res = client.put(
        "/api/v1/people/principal",
        headers=api_auth_headers,
        json={"person_id": p_id},
    )
    assert put_res.status_code == 200
    assert put_res.json() == {"principal_person_id": p_id, "display_name": "API Principal User"}

    # 4. GET now returns setting
    get_res = client.get("/api/v1/people/principal", headers=api_auth_headers)
    assert get_res.status_code == 200
    assert get_res.json() == {"principal_person_id": p_id, "display_name": "API Principal User"}

    # 5. Delete person -> HTTP 409 Conflict with conflict_type: "principal_person"
    del_res = client.delete(f"/api/v1/people/{p_id}", headers=api_auth_headers)
    assert del_res.status_code == 409
    assert del_res.json()["detail"]["conflict_type"] == "principal_person"

    # 6. DELETE /people/principal -> 204 No Content
    del_p_res = client.delete("/api/v1/people/principal", headers=api_auth_headers)
    assert del_p_res.status_code == 204

    # 7. GET after DELETE -> nulls
    assert client.get("/api/v1/people/principal", headers=api_auth_headers).json() == {
        "principal_person_id": None,
        "display_name": None,
    }

    # Cleanup
    delete_person(p_id)


def test_relationship_to_principal_projection():
    unset_principal_person()
    p_principal = _helper_create_person("Main User")
    p_target = _helper_create_person("Friend Person")
    principal_id = p_principal["person_id"]
    target_id = p_target["person_id"]

    today_str = "2026-09-11"

    # 1. When principal unset -> returns None
    assert get_relationship_to_principal_for_ai(target_id, None, None, today_str) is None

    # 2. When target is principal -> is_principal: True, relations: []
    rel_self = get_relationship_to_principal_for_ai(principal_id, principal_id, "Main User", today_str)
    assert rel_self == {
        "principal_person_id": principal_id,
        "principal_display_name": "Main User",
        "is_principal": True,
        "relations": [],
    }

    # 3. When target has no direct relation -> is_principal: False, relations: []
    rel_none = get_relationship_to_principal_for_ai(target_id, principal_id, "Main User", today_str)
    assert rel_none == {
        "principal_person_id": principal_id,
        "principal_display_name": "Main User",
        "is_principal": False,
        "relations": [],
    }

    # 4. Create directed relation: Target -> Principal (e.g. Target is child of Principal)
    rel_type = create_person_relation_type(
        slug="parent_child_test",
        forward_label="親",
        reverse_label="子",
        directionality="directed",
    )
    type_id = rel_type["relation_type_id"]

    # Target is subject (親), Principal is object (子)
    create_person_relation(
        person_id=target_id,
        subject_person_id=target_id,
        object_person_id=principal_id,
        relation_type_id=type_id,
        started_on="2020-01-01",
        ended_on=None,
    )

    rel_proj = get_relationship_to_principal_for_ai(target_id, principal_id, "Main User", today_str)
    assert rel_proj["is_principal"] is False
    assert len(rel_proj["relations"]) == 1
    rel_item = rel_proj["relations"][0]
    assert rel_item["person_to_principal"] == "親"
    assert rel_item["principal_to_person"] == "子"
    assert rel_item["relation_type_slug"] == "parent_child_test"
    assert rel_item["status"] == "active"
    assert rel_item["started_on"] == "2020-01-01"
    assert rel_item["ended_on"] is None

    # Cleanup
    unset_principal_person()
    delete_person(target_id)
    delete_person(principal_id)


def test_people_get_tool_with_principal_context():
    unset_principal_person()
    p_principal = _helper_create_person("Alice Principal")
    p_target = _helper_create_person("Bob Target")
    p_id = p_principal["person_id"]
    t_id = p_target["person_id"]

    set_principal_person(p_id)

    trusted_ctx = {
        "principal_person_id": p_id,
        "principal_display_name": "Alice Principal",
        "now": datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
    }

    tools = resolve_tools_with_context(["people_get"], trusted_ctx)
    assert len(tools) == 1
    people_get_tool = tools[0]

    # Call people_get for Bob Target
    import json
    res_str = people_get_tool.invoke({"person_id": t_id})
    res = json.loads(res_str)

    assert "relationship_to_principal" in res
    assert res["relationship_to_principal"]["principal_person_id"] == p_id
    assert res["relationship_to_principal"]["principal_display_name"] == "Alice Principal"
    assert res["relationship_to_principal"]["is_principal"] is False

    # Call people_get for Alice Principal (self)
    res_self_str = people_get_tool.invoke({"person_id": p_id})
    res_self = json.loads(res_self_str)
    assert res_self["relationship_to_principal"]["is_principal"] is True

    # Cleanup
    unset_principal_person()
    delete_person(t_id)
    delete_person(p_id)

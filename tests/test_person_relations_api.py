import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub import memory
from obsidian_ai_hub.web.app import create_app


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


@pytest.fixture
def seed_people_data(test_memory_db_path):
    conn = memory.get_db_connection()
    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("peo_taro", "山田 太郎", "山田太郎"),
        )
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("peo_hanako", "鈴木 花子", "鈴木花子"),
        )
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("peo_jiro", "佐藤 次郎", "佐藤次郎"),
        )
    conn.close()
    return ["peo_taro", "peo_hanako", "peo_jiro"]


def test_relation_types_crud(seed_people_data, client):
    # 1. List relation types (includes built-in)
    res = client.get("/api/v1/person-relation-types")
    assert res.status_code == 200
    types = res.json()
    assert len(types) >= 25

    # 2. Create custom relation type
    create_body = {
        "slug": "custom-mentor",
        "forward_label": "メンターである",
        "reverse_label": "メンティーである",
        "directionality": "directed",
        "description": "指導関係",
    }
    res = client.post("/api/v1/person-relation-types", json=create_body)
    assert res.status_code == 201
    created_type = res.json()
    assert created_type["slug"] == "custom-mentor"
    assert created_type["is_builtin"] is False
    assert created_type["is_active"] is True

    # Duplicate slug -> 409
    res = client.post("/api/v1/person-relation-types", json=create_body)
    assert res.status_code == 409
    assert res.json()["detail"]["conflict_type"] == "slug_conflict"

    # 3. Update relation type (deactivate)
    type_id = created_type["relation_type_id"]
    res = client.patch(
        f"/api/v1/person-relation-types/{type_id}",
        json={"is_active": False, "description": "指導関係 (非活性)"},
    )
    assert res.status_code == 200
    updated_type = res.json()
    assert updated_type["is_active"] is False
    assert updated_type["description"] == "指導関係 (非活性)"


def test_person_relations_crud_and_status_filter(seed_people_data, client):
    # Get a built-in active relation_type_id
    res = client.get("/api/v1/person-relation-types")
    types = res.json()
    parent_type = next(t for t in types if t["slug"] == "parent-child")
    type_id = parent_type["relation_type_id"]

    # 1. Create Relation with url person_id mismatch -> 400
    rel_create_req = {
        "subject_person_id": "peo_taro",
        "object_person_id": "peo_hanako",
        "relation_type_id": type_id,
        "started_on": "2020-01-01",
        "ended_on": None,
        "note": "親子関係",
        "initial_evidence": [
            {
                "source_type": "manual",
                "quote": "太郎は花子の親である",
                "note": "戸籍記載",
                "observed_at": "2020-01-01",
            }
        ],
    }
    res = client.post("/api/v1/people/peo_jiro/relations", json=rel_create_req)
    assert res.status_code == 400

    # 2. Self-relation -> 409 Conflict
    self_rel_req = dict(rel_create_req, object_person_id="peo_taro")
    res = client.post("/api/v1/people/peo_taro/relations", json=self_rel_req)
    assert res.status_code == 409
    assert res.json()["detail"]["conflict_type"] == "self_relation"

    # 3. Valid Relation Creation -> 201 Created
    res = client.post("/api/v1/people/peo_taro/relations", json=rel_create_req)
    assert res.status_code == 201
    res_data = res.json()
    assert res_data["action"] == "created"
    rel = res_data["relation"]
    assert rel["subject_person_id"] == "peo_taro"
    assert rel["object_person_id"] == "peo_hanako"
    assert len(rel["evidence"]) == 1
    rel_id = rel["relation_id"]

    # 4. Duplicate Relation Creation -> 200 OK with merged_into_existing
    duplicate_req = dict(rel_create_req, note="追加メモ")
    res = client.post("/api/v1/people/peo_taro/relations", json=duplicate_req)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["action"] == "merged_into_existing"
    assert res_data["relation"]["relation_id"] == rel_id
    assert "親子関係" in res_data["relation"]["note"]
    assert "追加メモ" in res_data["relation"]["note"]

    # 5. List relations for person with status filter
    res = client.get("/api/v1/people/peo_taro/relations")
    assert res.status_code == 200
    all_rels = res.json()
    assert len(all_rels) == 1
    assert all_rels[0]["status"] == "active"

    # Status filter match
    res = client.get("/api/v1/people/peo_taro/relations?status=active")
    assert res.status_code == 200
    assert len(res.json()) == 1

    # Status filter non-match
    res = client.get("/api/v1/people/peo_taro/relations?status=ended")
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 6. Evidence CRUD
    ev_create_req = {
        "source_type": "manual",
        "quote": "新規根拠",
        "observed_at": "2021-05-05",
    }
    res = client.post(f"/api/v1/person-relations/{rel_id}/evidence", json=ev_create_req)
    assert res.status_code == 201
    updated_rel_with_ev = res.json()
    assert len(updated_rel_with_ev["evidence"]) == 2
    added_ev = next(e for e in updated_rel_with_ev["evidence"] if e["quote"] == "新規根拠")
    ev_id = added_ev["evidence_id"]

    # Update evidence
    res = client.patch(
        f"/api/v1/person-relation-evidence/{ev_id}",
        json={"quote": "更新後根拠", "note": "修正常記"},
    )
    assert res.status_code == 200

    # Delete evidence -> 204 No Content
    res = client.delete(f"/api/v1/person-relation-evidence/{ev_id}")
    assert res.status_code == 204

    # 7. Delete Relation -> 204 No Content
    res = client.delete(f"/api/v1/person-relations/{rel_id}")
    assert res.status_code == 204

    # Verify deleted
    res = client.get("/api/v1/people/peo_taro/relations")
    assert res.status_code == 200
    assert len(res.json()) == 0


def test_inactive_relation_type_rejected(seed_people_data, client):
    # 1. Create custom relation type
    create_body = {
        "slug": "custom-temp",
        "forward_label": "仮関係",
        "reverse_label": "仮関係",
        "directionality": "symmetric",
    }
    res = client.post("/api/v1/person-relation-types", json=create_body)
    type_id = res.json()["relation_type_id"]

    # Deactivate it
    client.patch(f"/api/v1/person-relation-types/{type_id}", json={"is_active": False})

    # Attempt relation creation using inactive type -> 409 Conflict
    rel_create_req = {
        "subject_person_id": "peo_taro",
        "object_person_id": "peo_hanako",
        "relation_type_id": type_id,
    }
    res = client.post("/api/v1/people/peo_taro/relations", json=rel_create_req)
    assert res.status_code == 409
    assert res.json()["detail"]["conflict_type"] == "inactive_relation_type"


def test_unauthenticated_requests_rejected(seed_people_data, api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    unauth_client = TestClient(app)

    res = unauth_client.get("/api/v1/person-relation-types")
    assert res.status_code == 401

    res = unauth_client.get("/api/v1/people/peo_taro/relations")
    assert res.status_code == 401


def test_nonexistent_ids_return_404(seed_people_data, client):
    # 1. Nonexistent person GET relations -> 404
    res = client.get("/api/v1/people/peo_nonexistent/relations")
    assert res.status_code == 404

    # 2. Nonexistent person POST relations -> 404
    res = client.get("/api/v1/person-relation-types")
    type_id = res.json()[0]["relation_type_id"]
    res = client.post(
        "/api/v1/people/peo_nonexistent/relations",
        json={
            "subject_person_id": "peo_nonexistent",
            "object_person_id": "peo_hanako",
            "relation_type_id": type_id,
        },
    )
    assert res.status_code == 404

    # 3. Nonexistent relation PATCH / DELETE -> 404
    res = client.patch(
        "/api/v1/person-relations/rel_nonexistent",
        json={"note": "updated note"},
    )
    assert res.status_code == 404

    res = client.delete("/api/v1/person-relations/rel_nonexistent")
    assert res.status_code == 404

    # 4. Nonexistent relation type PATCH -> 404
    res = client.patch(
        "/api/v1/person-relation-types/rlt_nonexistent",
        json={"description": "updated"},
    )
    assert res.status_code == 404

    # 5. Nonexistent relation evidence POST / PATCH / DELETE -> 404
    res = client.post(
        "/api/v1/person-relations/rel_nonexistent/evidence",
        json={"source_type": "manual", "quote": "test"},
    )
    assert res.status_code == 404

    res = client.patch(
        "/api/v1/person-relation-evidence/evi_nonexistent",
        json={"quote": "test"},
    )
    assert res.status_code == 404

    res = client.delete("/api/v1/person-relation-evidence/evi_nonexistent")
    assert res.status_code == 404

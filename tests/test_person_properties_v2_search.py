import sqlite3
import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.database import get_db_connection
from obsidian_ai_hub.web.app import create_app

app = create_app(token="test-token")
from obsidian_ai_hub.web.services.person_properties import (
    create_property_definition_in_tx,
    create_person_property_value_in_tx,
    search_people_by_properties,
)


def setup_test_data():
    conn = get_db_connection()
    from obsidian_ai_hub.web.services.person_properties import register_nfkc_casefold
    register_nfkc_casefold(conn)
    with conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM person_property_values")
        cursor.execute("DELETE FROM person_property_options")
        cursor.execute("DELETE FROM person_property_definition_aliases")
        cursor.execute("DELETE FROM person_property_definitions")
        cursor.execute("DELETE FROM person_aliases")
        cursor.execute("DELETE FROM people")

        # Create People
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("p_alice", "Alice Smith", "alicesmith"),
        )
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("p_bob", "Bob Jones", "bobjones"),
        )

        # Create Definitions
        d_skill = create_property_definition_in_tx(
            cursor, key="skills", display_name="Skills", data_type="text", cardinality="multiple"
        )
        d_role = create_property_definition_in_tx(
            cursor,
            key="role",
            display_name="Role",
            data_type="select",
            cardinality="single",
            options=[
                {"option_key": "engineer", "display_name": "Engineer"},
                {"option_key": "designer", "display_name": "Designer"},
            ],
        )
        d_age = create_property_definition_in_tx(
            cursor, key="age", display_name="Age", data_type="number", cardinality="single"
        )
        d_remote = create_property_definition_in_tx(
            cursor, key="is_remote", display_name="Is Remote", data_type="boolean", cardinality="single"
        )
        d_join = create_property_definition_in_tx(
            cursor, key="joined_on", display_name="Joined On", data_type="date", cardinality="single"
        )

        # Values for Alice
        create_person_property_value_in_tx(
            cursor, "p_alice", d_skill["property_definition_id"], "Python", valid_from="2020", is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_alice", d_skill["property_definition_id"], "Rust", valid_from="2024", is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_alice", d_role["property_definition_id"], "engineer", is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_alice", d_age["property_definition_id"], 30, is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_alice", d_remote["property_definition_id"], True, is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_alice", d_join["property_definition_id"], "2022-04-01", is_api_call=False
        )

        # Values for Bob
        create_person_property_value_in_tx(
            cursor, "p_bob", d_skill["property_definition_id"], "Python", valid_from="2021", is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_bob", d_role["property_definition_id"], "designer", is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_bob", d_age["property_definition_id"], 25, is_api_call=False
        )
        create_person_property_value_in_tx(
            cursor, "p_bob", d_remote["property_definition_id"], False, is_api_call=False
        )

    return {
        "skills": d_skill["property_definition_id"],
        "role": d_role["property_definition_id"],
        "age": d_age["property_definition_id"],
        "is_remote": d_remote["property_definition_id"],
        "joined_on": d_join["property_definition_id"],
    }


def test_search_people_types_and_operators():
    defs = setup_test_data()

    # Text contains
    res = search_people_by_properties(
        conditions=[{"property_definition_id": defs["skills"], "operator": "contains", "value": "python"}]
    )
    assert res["total"] == 2

    # Select eq
    res = search_people_by_properties(
        conditions=[{"property_definition_id": defs["role"], "operator": "eq", "value": "engineer"}]
    )
    assert res["total"] == 1
    assert res["items"][0]["person"]["person_id"] == "p_alice"

    # Number gte / lte / between
    res_gte = search_people_by_properties(
        conditions=[{"property_definition_id": defs["age"], "operator": "gte", "value": 28}]
    )
    assert res_gte["total"] == 1
    assert res_gte["items"][0]["person"]["person_id"] == "p_alice"

    res_between = search_people_by_properties(
        conditions=[{"property_definition_id": defs["age"], "operator": "between", "value_from": 20, "value_to": 35}]
    )
    assert res_between["total"] == 2

    # Boolean eq
    res_bool = search_people_by_properties(
        conditions=[{"property_definition_id": defs["is_remote"], "operator": "eq", "value": True}]
    )
    assert res_bool["total"] == 1
    assert res_bool["items"][0]["person"]["person_id"] == "p_alice"

    # Multiple skills AND on different rows
    res_multi = search_people_by_properties(
        conditions=[
            {"property_definition_id": defs["skills"], "operator": "contains", "value": "Python"},
            {"property_definition_id": defs["skills"], "operator": "contains", "value": "Rust"},
        ]
    )
    assert res_multi["total"] == 1
    assert res_multi["items"][0]["person"]["person_id"] == "p_alice"
    assert len(res_multi["items"][0]["matched_properties"]) == 2


def test_search_api_endpoint(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_API_TOKEN", "test-token")
    import obsidian_ai_hub.web.app as web_app
    monkeypatch.setattr(web_app, "TOKEN", "test-token")
    defs = setup_test_data()
    client = TestClient(app)

    headers = {"Authorization": "Bearer test-token"}

    # Valid POST /api/v1/people/search
    resp = client.post(
        "/api/v1/people/search",
        headers=headers,
        json={
            "name_query": "Alice",
            "conditions": [
                {"property_definition_id": defs["role"], "operator": "eq", "value": "engineer"}
            ],
            "valid_period": {"mode": "all"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["person"]["display_name"] == "Alice Smith"

    # Invalid Operator -> 422
    resp_invalid = client.post(
        "/api/v1/people/search",
        headers=headers,
        json={
            "conditions": [
                {"property_definition_id": defs["role"], "operator": "contains", "value": "engineer"}
            ]
        },
    )
    assert resp_invalid.status_code == 422


def test_v3_partial_date_crud_schemas(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_API_TOKEN", "test-token")
    import obsidian_ai_hub.web.app as web_app
    monkeypatch.setattr(web_app, "TOKEN", "test-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}

    conn = get_db_connection()
    with conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM person_property_values")
        cursor.execute("DELETE FROM person_property_definitions")
        cursor.execute("DELETE FROM people")
        cursor.execute(
            "INSERT INTO people (person_id, display_name, normalized_name) VALUES (?, ?, ?)",
            ("p_partial", "Partial Date Person", "partialdateperson"),
        )
        d_note = create_property_definition_in_tx(
            cursor, key="work_history", display_name="Work History", data_type="text", cardinality="multiple", source_type="database"
        )
        def_id = d_note["property_definition_id"]

    # Test Pydantic schema acceptance of YYYY and YYYY-MM
    resp = client.post(
        f"/api/v1/people/p_partial/properties",
        headers=headers,
        json={
            "property_definition_id": def_id,
            "value": "Company A",
            "valid_from": "2020",
            "valid_until": "2024-05",
        },
    )
    assert resp.status_code == 201
    res_val = resp.json()
    assert res_val["valid_from"] == "2020"
    assert res_val["valid_until"] == "2024-05"

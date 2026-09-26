"""User workflow templates and definition package import/export."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from obsidian_ai_hub.tasks import store as task_store
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.workflow import definition_package as package
from obsidian_ai_hub.workflow import store as workflow_store


@pytest.fixture
def client(api_token, api_auth_headers):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    return TestClient(app, headers=api_auth_headers)


def _loop_graph() -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "node_id": "cap",
            "node_type": "capability",
            "label": "cap",
            "config": {"capability_key": "vault_search", "inputs": {"query": "x"}},
        },
        {
            "node_id": "loop",
            "node_type": "loop",
            "label": "loop",
            "config": {
                "state_schema": {
                    "type": "object",
                    "properties": {"done": {"type": "boolean"}},
                    "required": ["done"],
                    "additionalProperties": False,
                },
                "input_mapping": {"done": False},
                "continuation_condition": {
                    "from_path": "loop.state.done",
                    "operator": "equals",
                    "value": False,
                },
                "max_iterations": 2,
                "entry_node_id": "child",
            },
        },
        {
            "node_id": "child",
            "node_type": "capability",
            "label": "child",
            "config": {"capability_key": "vault_search", "inputs": {"query": "y"}},
            "parent_loop_node_id": "loop",
        },
        {
            "node_id": "result",
            "node_type": "loop_result",
            "label": "result",
            "config": {"output_mapping": {"done": False}},
            "parent_loop_node_id": "loop",
        },
        {
            "node_id": "end",
            "node_type": "terminal",
            "label": "end",
            "config": {"outcome": "success"},
        },
    ]
    edges = [
        {
            "edge_id": "e_cap_loop",
            "source_node_id": "cap",
            "target_node_id": "loop",
            "order_index": 0,
        },
        {
            "edge_id": "e_loop_end",
            "source_node_id": "loop",
            "target_node_id": "end",
            "order_index": 0,
        },
        {
            "edge_id": "e_child_result",
            "source_node_id": "child",
            "target_node_id": "result",
            "order_index": 0,
        },
    ]
    return nodes, edges


def _publish_loop_workflow(client, name: str = "wf") -> tuple[str, str]:
    task_store.sync_capabilities()
    created = client.post("/api/v1/workflows", json={"name": name})
    workflow = created.json()
    workflow_id = workflow["workflow_id"]
    revision_id = workflow["revision"]["revision_id"]
    nodes, edges = _loop_graph()
    updated = client.put(
        f"/api/v1/workflows/revisions/{revision_id}",
        json={
            "inputs_schema": {"type": "object", "properties": {"topic": {"type": "string"}}},
            "nodes": nodes,
            "edges": edges,
        },
    )
    assert updated.status_code == 200, updated.text
    published = client.post(f"/api/v1/workflows/revisions/{revision_id}/publish")
    assert published.status_code == 200, published.text
    return workflow_id, revision_id


def _by_label(revision: dict) -> dict[str, dict]:
    return {str(node["label"]): node for node in revision["nodes"]}


# --- definition package (pure) --------------------------------------------


def test_package_json_yaml_equivalence():
    nodes, edges = _loop_graph()
    built = package.build_package(
        "pkg", "desc", {"type": "object"}, nodes, edges
    )
    from_json = package.parse_package(
        package.serialize_package(built, "json").encode(), "json"
    )
    from_yaml = package.parse_package(
        package.serialize_package(built, "yaml").encode(), "yaml"
    )
    assert from_json == from_yaml == built


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update({"version": 2}),
        lambda p: p.update({"format": "other"}),
        lambda p: p.update({"unexpected": 1}),
    ],
)
def test_package_rejects_bad_header(mutate):
    nodes, edges = _loop_graph()
    built = package.build_package("pkg", "", {"type": "object"}, nodes, edges)
    mutate(built)
    with pytest.raises(package.DefinitionPackageError):
        package.validate_package(built)


def test_package_rejects_invalid_yaml():
    with pytest.raises(package.DefinitionPackageError):
        package.parse_package(b": : not yaml :", "yaml")


def test_package_rejects_oversize():
    with pytest.raises(package.DefinitionPackageError):
        package.parse_package(b"x" * (package.MAX_PACKAGE_BYTES + 1), "json")


def test_package_rejects_duplicate_ids_and_bad_reference():
    nodes, edges = _loop_graph()
    built = package.build_package("pkg", "", {"type": "object"}, nodes, edges)
    built["nodes"][1]["node_id"] = built["nodes"][0]["node_id"]
    with pytest.raises(package.DefinitionPackageError):
        package.validate_package(built)

    nodes, edges = _loop_graph()
    built = package.build_package("pkg", "", {"type": "object"}, nodes, edges)
    built["edges"][0]["target_node_id"] = "missing"
    with pytest.raises(package.DefinitionPackageError):
        package.validate_package(built)


def test_package_rejects_malformed_edge_without_raising():
    # Missing source/target and a non-numeric order_index must surface as a
    # DefinitionPackageError (422), never a raw KeyError/ValueError (500).
    for edge in (
        {"edge_id": "e1"},
        {
            "edge_id": "e1",
            "source_node_id": "cap",
            "target_node_id": "end",
            "order_index": "abc",
        },
    ):
        body = {
            "format": package.PACKAGE_FORMAT,
            "version": 1,
            "name": "p",
            "description": "",
            "inputs_schema": {"type": "object"},
            "nodes": [],
            "edges": [edge],
        }
        with pytest.raises(package.DefinitionPackageError):
            package.validate_package(body)


def test_package_rejects_unhashable_reference_values():
    base = {
        "format": package.PACKAGE_FORMAT,
        "version": 1,
        "name": "p",
        "description": "",
        "inputs_schema": {"type": "object"},
        "edges": [],
    }
    node = {"node_id": "n", "node_type": "terminal", "config": {"outcome": "success"}}
    edge = {"edge_id": "e", "source_node_id": ["n"], "target_node_id": "n"}
    with pytest.raises(package.DefinitionPackageError):
        package.validate_package({**base, "nodes": [node], "edges": [edge]})

    loop = {
        "node_id": "loop",
        "node_type": "loop",
        "config": {"entry_node_id": {"a": 1}},
    }
    with pytest.raises(package.DefinitionPackageError):
        package.validate_package({**base, "nodes": [loop], "edges": []})


def test_package_rejects_deeply_nested_body():
    raw = b"[" * 5000
    with pytest.raises(package.DefinitionPackageError):
        package.parse_package(raw, "json")


def test_validate_graph_rejects_too_many_edges():
    from obsidian_ai_hub.workflow.validation import validate_graph

    nodes = [
        {"node_id": f"n{i}", "node_type": "terminal", "config": {"outcome": "success"}}
        for i in range(3)
    ]
    edges = [
        {
            "edge_id": f"e{i}",
            "source_node_id": "n0",
            "target_node_id": "n1",
            "order_index": i,
        }
        for i in range(61)
    ]
    errors = validate_graph(nodes=nodes, edges=edges)
    assert any("Edge 数が上限" in error for error in errors)


# --- export / import -------------------------------------------------------


def test_import_renumbers_structured_field_reference(test_memory_db_path, client):
    """A valid strict structured field ref survives import with a new node id."""
    task_store.sync_capabilities()
    package_body = {
        "format": package.PACKAGE_FORMAT,
        "version": 1,
        "name": "__opcheck_import_strict_ref",
        "description": "",
        "inputs_schema": {"type": "object"},
        "nodes": [
            {
                "node_id": "reader",
                "node_type": "capability",
                "label": "reader",
                "config": {
                    "capability_key": "vault_read_file",
                    "inputs": {"relative_path": "a.md"},
                    "fail_on_output_mismatch": True,
                },
            },
            {
                "node_id": "themer",
                "node_type": "agent",
                "label": "themer",
                "config": {
                    "agent_id": "agent_x",
                    "inputs": {
                        "body": {"$ref": "nodes.reader.output.content"}
                    },
                    "output_schema": {"type": "object"},
                },
            },
            {
                "node_id": "end",
                "node_type": "terminal",
                "label": "end",
                "config": {"outcome": "success"},
            },
        ],
        "edges": [
            {
                "edge_id": "e1",
                "source_node_id": "reader",
                "target_node_id": "themer",
                "edge_kind": "normal",
                "condition": None,
                "order_index": 0,
            },
            {
                "edge_id": "e2",
                "source_node_id": "themer",
                "target_node_id": "end",
                "edge_kind": "normal",
                "condition": None,
                "order_index": 0,
            },
        ],
    }
    imported = client.post(
        "/api/v1/workflows/import?format=json",
        content=json.dumps(package_body).encode(),
    )
    assert imported.status_code == 201, imported.text
    revision = imported.json()["revision"]
    labels = _by_label(revision)
    ref = labels["themer"]["config"]["inputs"]["body"]["$ref"]
    assert ref == f"nodes.{labels['reader']['node_id']}.output.content"


def test_export_import_roundtrip_renumbers_ids(test_memory_db_path, client):
    _, revision_id = _publish_loop_workflow(client, "source")
    exported = client.get(
        f"/api/v1/workflows/revisions/{revision_id}/export?format=json"
    )
    assert exported.status_code == 200
    exported_package = exported.json()

    original = client.get(f"/api/v1/workflows/revisions/{revision_id}").json()
    original_labels = _by_label(original)

    imported = client.post(
        "/api/v1/workflows/import?format=json",
        content=json.dumps(exported_package).encode(),
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["validation_errors"] == []
    imported_revision = result["revision"]
    imported_labels = _by_label(imported_revision)

    assert set(imported_labels) == set(original_labels)
    original_ids = {n["node_id"] for n in original["nodes"]}
    imported_ids = {n["node_id"] for n in imported_revision["nodes"]}
    assert original_ids.isdisjoint(imported_ids)

    loop = imported_labels["loop"]
    assert loop["config"]["entry_node_id"] == imported_labels["child"]["node_id"]
    assert imported_labels["child"]["parent_loop_node_id"] == loop["node_id"]
    assert (
        imported_labels["result"]["config"]["output_mapping"]["done"] is False
    )
    assert loop["config"]["continuation_condition"]["from_path"] == "loop.state.done"
    assert imported_revision["inputs_schema"] == original["inputs_schema"]
    # A new workflow with a draft revision; nothing published or run.
    assert imported_revision["status"] == "draft"
    assert result["workflow"]["workflow_id"] != original["workflow_id"]


def test_export_rejects_draft(test_memory_db_path, client):
    created = client.post("/api/v1/workflows", json={"name": "draft-only"})
    revision_id = created.json()["revision"]["revision_id"]
    response = client.get(
        f"/api/v1/workflows/revisions/{revision_id}/export?format=yaml"
    )
    assert response.status_code == 409


def test_import_structural_failure_writes_nothing(test_memory_db_path, client):
    before = workflow_store.list_workflows(limit=100)[1]
    response = client.post(
        "/api/v1/workflows/import?format=yaml",
        content=b"format: wrong\nversion: 1\n",
    )
    assert response.status_code == 422
    after = workflow_store.list_workflows(limit=100)[1]
    assert after == before


def test_import_unresolved_agent_creates_draft_only(test_memory_db_path, client):
    task_store.sync_capabilities()
    package_body = {
        "format": package.PACKAGE_FORMAT,
        "version": 1,
        "name": "__opcheck_import_agent",
        "description": "",
        "inputs_schema": {"type": "object"},
        "nodes": [
            {
                "node_id": "a",
                "node_type": "agent",
                "label": "agent",
                "config": {
                    "agent_id": "does-not-exist",
                    "inputs": {},
                    "output_schema": {"type": "object"},
                },
            },
            {
                "node_id": "t",
                "node_type": "terminal",
                "label": "end",
                "config": {"outcome": "success"},
            },
        ],
        "edges": [
            {
                "edge_id": "e1",
                "source_node_id": "a",
                "target_node_id": "t",
                "edge_kind": "normal",
                "condition": None,
                "order_index": 0,
            }
        ],
    }
    imported = client.post(
        "/api/v1/workflows/import?format=json",
        content=json.dumps(package_body).encode(),
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    assert result["validation_errors"]
    revision_id = result["revision"]["revision_id"]
    assert client.post(
        f"/api/v1/workflows/revisions/{revision_id}/publish"
    ).status_code == 422
    assert client.post(
        f"/api/v1/workflows/revisions/{revision_id}/runs", json={"inputs": {}}
    ).status_code == 409


def test_import_requires_auth(test_memory_db_path, api_token):
    app = create_app(host="127.0.0.1", port=0, token=api_token)
    unauthenticated = TestClient(app)
    response = unauthenticated.post(
        "/api/v1/workflows/import?format=json", content=b"{}"
    )
    assert response.status_code == 401


# --- user templates --------------------------------------------------------


def test_user_template_lifecycle(test_memory_db_path, client):
    workflow_id, revision_id = _publish_loop_workflow(client, "templated")
    created = client.post(
        "/api/v1/workflows/user-templates",
        json={"source_revision_id": revision_id, "name": "my-template"},
    )
    assert created.status_code == 201, created.text
    template = created.json()
    template_id = template["template_id"]
    assert template["source_workflow_id"] == workflow_id

    listed = client.get("/api/v1/workflows/user-templates")
    assert listed.status_code == 200
    assert [t["template_id"] for t in listed.json()["items"]] == [template_id]
    assert "definition" not in listed.json()["items"][0]

    # Source workflow deletion must not affect the template.
    assert client.delete(f"/api/v1/workflows/{workflow_id}").status_code == 200
    instantiated = client.post(
        f"/api/v1/workflows/user-templates/{template_id}/instantiate",
        json={"name": "from-template"},
    )
    assert instantiated.status_code == 201, instantiated.text
    generated_id = instantiated.json()["workflow"]["workflow_id"]
    assert generated_id != workflow_id

    # Template deletion leaves the generated workflow intact.
    assert client.delete(
        f"/api/v1/workflows/user-templates/{template_id}"
    ).status_code == 200
    assert client.get(f"/api/v1/workflows/{generated_id}").status_code == 200
    assert client.get(
        f"/api/v1/workflows/user-templates/{template_id}"
    ).status_code == 404


def test_user_template_content_update(test_memory_db_path, client):
    _, revision_id = _publish_loop_workflow(client, "first")
    template = client.post(
        "/api/v1/workflows/user-templates",
        json={"source_revision_id": revision_id, "name": "tpl"},
    ).json()
    template_id = template["template_id"]

    # A second published revision with a different input schema.
    created = client.post("/api/v1/workflows", json={"name": "second"})
    second_revision_id = created.json()["revision"]["revision_id"]
    nodes, edges = _loop_graph()
    client.put(
        f"/api/v1/workflows/revisions/{second_revision_id}",
        json={
            "inputs_schema": {
                "type": "object",
                "properties": {"other": {"type": "string"}},
            },
            "nodes": nodes,
            "edges": edges,
        },
    )
    assert client.post(
        f"/api/v1/workflows/revisions/{second_revision_id}/publish"
    ).status_code == 200

    updated = client.put(
        f"/api/v1/workflows/user-templates/{template_id}",
        json={"source_revision_id": second_revision_id, "description": "replaced"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["source_revision_id"] == second_revision_id
    assert updated.json()["description"] == "replaced"
    assert "other" in updated.json()["definition"]["inputs_schema"]["properties"]

    # Template creation from a draft revision is rejected.
    draft_revision_id = client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/revisions"
    ).json()["revision_id"]
    rejected = client.post(
        "/api/v1/workflows/user-templates",
        json={"source_revision_id": draft_revision_id},
    )
    assert rejected.status_code == 409


def test_user_template_export_formats(test_memory_db_path, client):
    _, revision_id = _publish_loop_workflow(client, "exportable")
    template_id = client.post(
        "/api/v1/workflows/user-templates",
        json={"source_revision_id": revision_id},
    ).json()["template_id"]
    as_json = client.get(
        f"/api/v1/workflows/user-templates/{template_id}/export?format=json"
    )
    as_yaml = client.get(
        f"/api/v1/workflows/user-templates/{template_id}/export?format=yaml"
    )
    assert as_json.status_code == 200
    assert as_yaml.status_code == 200
    assert as_json.headers["content-disposition"].startswith("attachment;")
    assert package.parse_package(as_json.content, "json") == package.parse_package(
        as_yaml.content, "yaml"
    )


def test_export_filename_is_rfc5987_for_non_ascii_name(test_memory_db_path, client):
    _, revision_id = _publish_loop_workflow(client, "__opcheck_日本語ワークフロー")
    response = client.get(
        f"/api/v1/workflows/revisions/{revision_id}/export?format=json"
    )
    assert response.status_code == 200, response.text
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition


def test_create_workflow_from_graph_rolls_back_on_failure(test_memory_db_path):
    before = workflow_store.list_workflows(limit=100)[1]
    nodes = [
        {
            "node_id": "n1",
            "node_type": "terminal",
            "label": "x",
            "config": {"outcome": object()},
        }
    ]
    with pytest.raises(TypeError):
        workflow_store.create_workflow_from_graph(
            "__opcheck_atomic", "", {"type": "object"}, nodes, []
        )
    assert workflow_store.list_workflows(limit=100)[1] == before


def test_code_templates_unchanged(test_memory_db_path, client):
    task_store.sync_capabilities()
    listed = client.get("/api/v1/workflows/templates")
    assert listed.status_code == 200
    assert {t["template_key"] for t in listed.json()["items"]} == {
        "plan_review_execute",
        "contextual_research",
    }
    created = client.post(
        "/api/v1/workflows/from-template",
        json={"template_key": "contextual_research"},
    )
    assert created.status_code == 201
    revision = created.json()["revision"]
    assert len(revision["nodes"]) == 4
    assert all(node["ui_position"] for node in revision["nodes"])

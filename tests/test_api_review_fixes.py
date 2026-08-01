import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.routes.deps import _is_loopback_host


def test_is_loopback_host_mapped_ipv6():
    # Loopback hosts
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::ffff:127.0.0.1") is True
    assert _is_loopback_host("::FFFF:127.0.0.1") is True

    # Non-loopback hosts
    assert _is_loopback_host("192.168.1.1") is False
    assert _is_loopback_host("::ffff:192.168.1.1") is False
    assert _is_loopback_host("::FFFF:192.168.1.1") is False
    assert _is_loopback_host("google.com") is False
    assert _is_loopback_host("") is False
    assert _is_loopback_host(None) is False


def test_vault_report_and_sync_endpoints(test_memory_db_path):
    app = create_app(host="127.0.0.1", port=0, token="")
    client = TestClient(app)

    # 1. GET /api/v1/people/vault-report - response does NOT contain synced
    res_report = client.get("/api/v1/people/vault-report")
    assert res_report.status_code == 200
    report_json = res_report.json()
    assert "synced" not in report_json
    assert "loader_report" in report_json
    assert "db_conflicts" in report_json

    # 2. POST /api/v1/people/sync - response DOES contain synced: True
    res_sync = client.post("/api/v1/people/sync")
    assert res_sync.status_code == 200
    sync_json = res_sync.json()
    assert sync_json["synced"] is True


def test_exception_information_leak_prevention(test_memory_db_path):
    app = create_app(host="127.0.0.1", port=0, token="")

    # We must configure TestClient with raise_server_exceptions=False so it returns 500 response
    # instead of raising the actual server exception inside pytest!
    client = TestClient(app, raise_server_exceptions=False)

    # Mock service.get_vault_report_dynamic to raise an unexpected Exception with an internal path
    with patch("obsidian_ai_hub.web.service.get_vault_report_dynamic", side_effect=Exception("Database error in /home/user/app/db/sqlite3.db")):
        response = client.get("/api/v1/people/vault-report")
        assert response.status_code == 500
        # Check that the detail string / internal path is NOT in the response
        assert "sqlite3.db" not in response.text
        assert "Database error" not in response.text

    # Mock service.sync_people to raise an unexpected Exception
    with patch("obsidian_ai_hub.web.service.sync_people", side_effect=Exception("Database error in /home/user/app/db/sqlite3.db")):
        response = client.post("/api/v1/people/sync")
        assert response.status_code == 500
        assert "sqlite3.db" not in response.text
        assert "Database error" not in response.text

    # Mock service.get_task_config to raise an unexpected Exception
    with patch("obsidian_ai_hub.web.service.get_task_config", side_effect=Exception("Config error in /home/user/app/config.yml")):
        response = client.get("/api/v1/task-config")
        assert response.status_code == 500
        assert "config.yml" not in response.text
        assert "Config error" not in response.text

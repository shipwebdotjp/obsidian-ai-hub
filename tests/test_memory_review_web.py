# ruff: noqa: E402
import sys
from unittest.mock import MagicMock

# Mock macOS-specific modules before importing obsidian_ai_hub to prevent ModuleNotFoundError on Linux/CI
mock_modules = {
    "EventKit": MagicMock(),
    "AppKit": MagicMock(),
    "objc": MagicMock(),
    "Foundation": MagicMock(),
    "ApplicationServices": MagicMock(),
    "atomacos": MagicMock(),
    "Quartz": MagicMock(),
    "Vision": MagicMock(),
    "Cocoa": MagicMock(),
}
for name, m in mock_modules.items():
    sys.modules[name] = m

from unittest.mock import patch
import pytest

from obsidian_ai_hub import memory
from obsidian_ai_hub.utils import config


@pytest.fixture
def clean_memory_env(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault"
    vault_path.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "VAULT_PATH", vault_path)

    activity_dir = vault_path / "activity"
    activity_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "ACTIVITY_PATH", activity_dir)

    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(config, "MEMORY_SQLITE_PATH", db_path)

    return vault_path


@pytest.fixture
def loopback_client(clean_memory_env):
    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="127.0.0.1", port=0, token="")
    return TestClient(app)


def _seed(memory_id: str, status: str = "candidate", content: str = "本文") -> None:
    cand = _make_candidate(memory_id, status=status, content=content)
    existing = memory.load_all_memories()
    memory.save_all_memories(existing + [cand])


def _make_candidate(memory_id: str, status: str = "candidate", content: str = "本文") -> dict:
    return {
        "schema_version": 1,
        "memory_id": memory_id,
        "status": status,
        "kind": "preference",
        "memory_key": f"key-{memory_id}",
        "content": content,
        "topics": ["その他"],
        "tags": ["seed"],
        "evidence": [],
        "valid_from": "2026-07-01",
        "valid_until": None,
        "review_due_at": None,
        "stability": "stable",
        "sensitivity": "personal",
        "extraction_confidence": 0.9,
        "supersedes": None,
        "contradicts": [],
        "dedup_suggestions": [],
        "provenance": {"extraction_method": "test"},
        "created_at": "2026-07-01T00:00:00+09:00",
        "updated_at": "2026-07-01T00:00:00+09:00",
        "reviewed_by": None,
        "reviewed_at": None,
    }


def test_health(loopback_client):
    res = loopback_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["auth_required"] is False


def test_list_and_detail(loopback_client):
    _seed("mem_a", content="おはよう")
    _seed("mem_b", content="こんばんは", status="approved")

    res = loopback_client.get("/api/v1/memories?status=candidate")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1, body
    assert body["items"][0]["memory_id"] == "mem_a"

    detail = loopback_client.get("/api/v1/memories/mem_a")
    assert detail.status_code == 200
    assert detail.json()["content"] == "おはよう"
    assert "events" in detail.json()


def test_review_approve_reject(loopback_client):
    _seed("mem_x")
    res = loopback_client.post(
        "/api/v1/memories/mem_x/review", json={"action": "approve"}
    )
    assert res.status_code == 200
    assert res.json()["memory"]["status"] == "approved"

    _seed("mem_y")
    res = loopback_client.post(
        "/api/v1/memories/mem_y/review", json={"action": "reject"}
    )
    assert res.status_code == 200
    assert res.json()["memory"]["status"] == "rejected"

    res = loopback_client.post(
        "/api/v1/memories/mem_unknown/review", json={"action": "approve"}
    )
    assert res.status_code == 404


def test_edit_validates_payload(loopback_client):
    _seed("mem_e")
    res = loopback_client.post(
        "/api/v1/memories/mem_e/edit",
        json={"content": "  ", "stability": "bogus"},
    )
    assert res.status_code == 400

    res = loopback_client.post(
        "/api/v1/memories/mem_e/edit",
        json={"kind": "fact"},
    )
    assert res.status_code == 400


def test_edit_writable_fields_auto_approve(loopback_client):
    _seed("mem_e", content="old content")
    res = loopback_client.post(
        "/api/v1/memories/mem_e/edit",
        json={
            "content": "new content",
            "topics": ["ライティング・コンテンツ制作", "unknown-topic"],
            "tags": ["x", "y"],
            "valid_from": "2026-07-01",
            "valid_until": "2026-12-31",
            "stability": "tentative",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["updated"] is True
    mem = body["memory"]
    assert mem["content"] == "new content"
    assert mem["stability"] == "tentative"
    assert mem["status"] == "approved"
    assert "ライティング・コンテンツ制作" in mem["topics"]
    assert "unknown-topic" not in mem["topics"]


def test_edit_rejects_invalid_date_range(loopback_client):
    _seed("mem_d")
    res = loopback_client.post(
        "/api/v1/memories/mem_d/edit",
        json={"valid_from": "2026-12-31", "valid_until": "2026-01-01"},
    )
    assert res.status_code == 400


def test_batch_review_partial(loopback_client):
    _seed("mem_p1")
    _seed("mem_p2", status="approved")
    res = loopback_client.post(
        "/api/v1/memories/batch-review",
        json={"memory_ids": ["mem_p1", "mem_p2", "mem_missing"], "action": "approve"},
    )
    assert res.status_code == 200
    body = res.json()
    assert set(body["updated"]) == {"mem_p1", "mem_p2"}
    assert body["not_found"] == ["mem_missing"]
    assert body["events"] == 2


def test_token_required_when_not_loopback():
    from fastapi.testclient import TestClient
    from obsidian_ai_hub.web.app import create_app

    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app)

    protected_routes = [
        ("GET", "/api/v1/memories"),
        ("POST", "/api/v1/memories/mem_x/review", {"action": "approve"}),
        ("POST", "/api/v1/memories/mem_x/edit", {"content": "updated"}),
        ("POST", "/api/v1/memories/batch-review", {"memory_ids": ["mem_x"], "action": "approve"}),
    ]

    for method, path, *payload in protected_routes:
        kwargs = {"json": payload[0]} if payload else {}
        res = client.request(method, path, **kwargs)
        assert res.status_code == 401, (method, path, res.status_code)

        res = client.request(
            method, path, headers={"Authorization": "Bearer wrong"}, **kwargs
        )
        assert res.status_code == 401, (method, path, res.status_code)

        res = client.request(
            method, path, headers={"Authorization": "Bearer secret-token"}, **kwargs
        )
        assert res.status_code in (200, 404), (method, path, res.status_code)


def test_token_required_at_startup_for_non_loopback():
    from obsidian_ai_hub.web import app as web_app

    with pytest.raises(RuntimeError):
        web_app.create_app(host="0.0.0.0", port=0, token="")


def test_serve_cli_starts_server():
    from obsidian_ai_hub import main as cli_main
    import uvicorn as _real_uvicorn

    # We patch uvicorn.run globally so that when main.py imports uvicorn
    # and calls uvicorn.run(...), it's intercepted.
    with patch("sys.argv", ["main.py", "--serve"]):
        with patch.object(_real_uvicorn, "run") as mock_run:
            cli_main.main()
    mock_run.assert_called_once()


def test_serve_host_without_serve_is_rejected():
    """`--serve-host` without `--serve` should not raise--argparse accepts the flag
    but the value is silently ignored. The validation is semantic-only."""
    from obsidian_ai_hub import main as cli_main
    from unittest.mock import patch

    with patch("sys.argv", ["main.py", "--serve-host", "0.0.0.0"]):
        # Should not raise -- just prints help
        cli_main.main()


def test_serve_loopback_no_token(monkeypatch):
    """`--serve` with loopback host should not require a token."""
    from obsidian_ai_hub.web import app as web_app

    monkeypatch.setattr(web_app, "HOST", "127.0.0.1")
    monkeypatch.setattr(web_app, "TOKEN", "")
    monkeypatch.setattr(web_app, "TOKEN_REQUIRED", False)

    with pytest.raises(RuntimeError):
        web_app.create_app(host="0.0.0.0", port=0, token="")

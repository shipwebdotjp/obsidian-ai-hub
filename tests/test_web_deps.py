from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.routes.deps import _is_loopback_host, _is_tailnet_host


def test_is_loopback_host():
    assert _is_loopback_host("127.0.0.1") is True
    assert _is_loopback_host("::1") is True
    assert _is_loopback_host("localhost") is True
    assert _is_loopback_host("::ffff:127.0.0.1") is True
    assert _is_loopback_host("::ffff:7f00:1") is True
    assert _is_loopback_host("::FFFF:7F00:0001") is True
    assert _is_loopback_host("testclient") is False
    assert _is_loopback_host("192.168.1.5") is False
    assert _is_loopback_host(None) is False
    assert _is_loopback_host("") is False


def test_is_tailnet_host():
    assert _is_tailnet_host("100.64.0.0") is True
    assert _is_tailnet_host("100.73.5.87") is True
    assert _is_tailnet_host("100.127.255.255") is True
    assert _is_tailnet_host("100.128.0.0") is False
    assert _is_tailnet_host("100.63.255.255") is False
    assert _is_tailnet_host("fd7a:115c:a1e0::1") is True
    assert _is_tailnet_host("fd7a:115c:a1e0:ffff::1") is True
    assert _is_tailnet_host("fd7a:115c:a1df::1") is False
    assert _is_tailnet_host("fd7a:115c:a1e1::1") is False
    assert _is_tailnet_host("192.168.1.5") is False
    assert _is_tailnet_host("127.0.0.1") is False
    assert _is_tailnet_host("localhost") is False
    assert _is_tailnet_host("not-an-ip") is False
    assert _is_tailnet_host(None) is False


def test_require_loopback_or_token_allows_ipv4_mapped_loopback():
    """IPv4-mapped IPv6 loopback must be exempt from token auth."""
    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app, client=("::ffff:127.0.0.1", 50000))
    res = client.get("/api/v1/memories")
    assert res.status_code in (200, 404)


def test_require_loopback_or_token_rejects_non_loopback():
    app = create_app(host="0.0.0.0", port=0, token="secret-token")
    client = TestClient(app, client=("192.168.1.5", 50000))
    res = client.get("/api/v1/memories")
    assert res.status_code == 401


def test_require_localhost_allows_ipv4_mapped_loopback():
    app = create_app(host="127.0.0.1", port=0, token="")
    for client_host in ("::ffff:127.0.0.1", "::FFFF:7F00:1", "127.0.0.1"):
        client = TestClient(app, client=(client_host, 50000))
        res = client.get("/api/v1/task-config")
        assert res.status_code == 200, client_host


def test_require_localhost_rejects_lan():
    app = create_app(host="127.0.0.1", port=0, token="")
    client = TestClient(app, client=("192.168.1.5", 50000))
    res = client.get("/api/v1/task-config")
    assert res.status_code == 403


def test_tailnet_allows_token_when_enabled(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    client = TestClient(app, client=("100.73.5.87", 50000))
    res = client.get(
        "/api/v1/task-config",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200


def test_tailnet_rejects_missing_token_when_enabled(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    client = TestClient(app, client=("100.73.5.87", 50000))
    res = client.get("/api/v1/task-config")
    assert res.status_code == 401


def test_tailnet_rejects_bad_token_when_enabled(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    client = TestClient(app, client=("100.73.5.87", 50000))
    res = client.get(
        "/api/v1/task-config",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 401


def test_tailnet_rejects_when_disabled(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "0")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    client = TestClient(app, client=("100.73.5.87", 50000))
    res = client.get(
        "/api/v1/task-config",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 403


def test_tailnet_rejects_external_ip_with_token(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    for client_host in ("192.168.1.5", "8.8.8.8"):
        client = TestClient(app, client=(client_host, 50000))
        res = client.get(
            "/api/v1/task-config",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert res.status_code == 403, client_host


def test_tailnet_ipv6_allows_token(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    app = create_app(host="127.0.0.1", port=0, token="secret-token")
    client = TestClient(app, client=("fd7a:115c:a1e0::1", 50000))
    res = client.get(
        "/api/v1/task-config",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert res.status_code == 200


def test_allow_tailnet_requires_token_at_startup(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS", "1")
    monkeypatch.delenv("OBSIDIAN_AI_HUB_API_TOKEN", raising=False)
    import pytest

    from obsidian_ai_hub.web.app import create_app

    with pytest.raises(RuntimeError):
        create_app(host="127.0.0.1", port=0, token="")

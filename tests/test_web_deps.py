from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app
from obsidian_ai_hub.web.routes.deps import _is_loopback_host


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

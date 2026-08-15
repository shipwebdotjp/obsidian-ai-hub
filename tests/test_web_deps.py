from fastapi.testclient import TestClient

from obsidian_ai_hub.web.app import create_app

TEST_API_TOKEN = "test-api-token"


def bearer_headers(token: str = TEST_API_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _anon_client(host: str = "0.0.0.0", token: str = TEST_API_TOKEN):
    """Client that does NOT send an Authorization header."""
    app = create_app(host=host, port=0, token=token)
    return TestClient(app)


def test_requires_token_always_even_loopback():
    """Even a loopback client must present a bearer token."""
    app = create_app(host="127.0.0.1", port=0, token=TEST_API_TOKEN)
    client = TestClient(app, client=("127.0.0.1", 50000))
    res = client.get("/api/v1/memories")
    assert res.status_code == 401
    assert res.headers.get("www-authenticate") == "Bearer"


def test_ipv4_mapped_loopback_without_token_rejected():
    """IPv4-mapped IPv6 loopback must NOT bypass token auth."""
    client = TestClient(
        create_app(host="0.0.0.0", port=0, token=TEST_API_TOKEN),
        client=("::ffff:127.0.0.1", 50000),
    )
    res = client.get("/api/v1/memories")
    assert res.status_code == 401


def test_valid_token_allowed():
    app = create_app(host="0.0.0.0", port=0, token=TEST_API_TOKEN)
    client = TestClient(
        app, client=("192.168.1.5", 50000), headers=bearer_headers()
    )
    res = client.get("/api/v1/memories?status=candidate")
    assert res.status_code == 200


def test_missing_token_rejected():
    client = _anon_client()
    res = client.get("/api/v1/memories")
    assert res.status_code == 401


def test_bad_token_rejected():
    app = create_app(host="0.0.0.0", port=0, token=TEST_API_TOKEN)
    client = TestClient(
        app, client=("192.168.1.5", 50000), headers=bearer_headers("wrong")
    )
    res = client.get("/api/v1/memories")
    assert res.status_code == 401


def test_all_routes_require_auth():
    """Every registered API route must carry the bearer-token dependency."""
    import obsidian_ai_hub.web.routes.deps as deps

    app = create_app(host="0.0.0.0", port=0, token=TEST_API_TOKEN)
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        if not hasattr(route, "dependant"):
            raise AssertionError(
                f"route {path} is not a FastAPI route; cannot verify bearer-token coverage"
            )
        deps_of_route = route.dependant.dependencies
        assert any(
            d.call is deps.require_bearer_token for d in deps_of_route
        ), f"route {path} lacks require_bearer_token"


def test_empty_token_rejected_at_startup():
    """create_app must fail to start without any bearer token."""
    import pytest

    with pytest.raises(RuntimeError):
        create_app(host="127.0.0.1", port=0, token="")

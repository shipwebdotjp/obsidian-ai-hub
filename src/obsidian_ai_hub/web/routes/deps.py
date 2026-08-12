import hmac
import ipaddress

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param


def _is_loopback_host(host: str | None) -> bool:
    """Return True when the host is a loopback address.

    Handles the ``localhost`` hostname, plain IPv4/IPv6 loopbacks, and
    IPv4-mapped IPv6 loopback addresses (``::ffff:127.0.0.1``).
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped
        if mapped is not None and mapped.is_loopback:
            return True
    return False


def require_loopback_or_token(request: Request) -> None:
    """
    Enforce bearer-token authentication when the server is bound to a
    non-loopback interface. Localhost binds (127.0.0.1, ::1) are exempt.
    """
    from obsidian_ai_hub.web.app import (  # local import to avoid cycle
        TOKEN,
        TOKEN_REQUIRED,
    )

    client_host = request.client.host if request.client else None
    if _is_loopback_host(client_host):
        return

    if not TOKEN_REQUIRED:
        return

    auth = request.headers.get("authorization")
    scheme, param = get_authorization_scheme_param(auth or "")
    if scheme.lower() != "bearer" or not param or not hmac.compare_digest(param, TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


_TAILNET_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_TAILNET_IPV6_NETWORK = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _is_tailnet_host(host: str | None) -> bool:
    """Return True when the host lies inside the Tailscale tailnet address space.

    Covers the IPv4 CGNAT range (``100.64.0.0/10``) used for tailnet peers and
    the IPv6 ULA prefix (``fd7a:115c:a1e0::/48``) used for IPv6 tailnet peers.
    """
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr in _TAILNET_IPV4_NETWORK or addr in _TAILNET_IPV6_NETWORK


def _valid_bearer_token(request: Request) -> bool:
    from obsidian_ai_hub.web.app import TOKEN  # local import to avoid cycle

    auth = request.headers.get("authorization")
    scheme, param = get_authorization_scheme_param(auth or "")
    return (
        scheme.lower() == "bearer"
        and bool(param)
        and TOKEN
        and hmac.compare_digest(param, TOKEN)
    )


def require_localhost_or_tailnet_token(request: Request) -> None:
    """Allow loopback clients unconditionally and, when enabled, tailnet clients
    that present a valid bearer token.

    Tailnet allowance only applies when ``OBSIDIAN_AI_HUB_ALLOW_TAILNET_TASKS`` is
    enabled in the running app (fail-closed by default). Non-loopback,
    non-tailnet clients are always rejected with ``403``.
    """
    from obsidian_ai_hub.web.app import ALLOW_TAILNET_TASKS

    client_host = request.client.host if request.client else None
    if not client_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Client IP not resolved.",
        )

    if client_host == "testclient" or _is_loopback_host(client_host):
        return

    if _is_tailnet_host(client_host) and ALLOW_TAILNET_TASKS:
        if _valid_bearer_token(request):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Forbidden: This feature is only available on localhost or, when "
            "enabled, over the Tailscale tailnet."
        ),
    )


def require_localhost(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if not client_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Client IP not resolved."
        )

    if client_host == "testclient" or _is_loopback_host(client_host):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: This feature is only available on localhost (the same machine running this app)."
    )

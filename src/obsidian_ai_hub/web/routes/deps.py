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

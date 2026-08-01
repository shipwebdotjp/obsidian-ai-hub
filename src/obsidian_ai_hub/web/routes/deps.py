import hmac
import ipaddress

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param


def require_loopback_or_token(request: Request) -> None:
    """
    Enforce bearer-token authentication when the server is bound to a
    non-loopback interface. Localhost binds (127.0.0.1, ::1) are exempt.
    """
    from obsidian_ai_hub.web.app import (  # local import to avoid cycle
        LOOPBACK_HOSTS,
        TOKEN,
        TOKEN_REQUIRED,
    )

    client_host = request.client.host if request.client else None
    if client_host in LOOPBACK_HOSTS:
        return

    if not TOKEN_REQUIRED:
        return

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
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

    if client_host in {"localhost", "testclient"}:
        return

    try:
        ip = ipaddress.ip_address(client_host)
        if ip.is_loopback:
            return
    except ValueError:
        pass

    # Support IPv4-mapped IPv6 loopback addresses like ::ffff:127.0.0.1
    cleaned_host = client_host
    if client_host.startswith("::ffff:"):
        cleaned_host = client_host[7:]

    try:
        ip = ipaddress.ip_address(cleaned_host)
        if ip.is_loopback:
            return
    except ValueError:
        pass

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: This feature is only available on localhost (the same machine running this app)."
    )

import hmac

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param


def require_bearer_token(request: Request) -> None:
    """Require a valid bearer token for every API request.

    Authentication is unconditional: loopback, LAN, and public clients all must
    present a matching ``Authorization: Bearer <token>`` header. External
    exposure is expected to terminate TLS at a reverse proxy that forwards
    requests to this app bound to localhost.
    """
    from obsidian_ai_hub.web.app import TOKEN  # local import to avoid cycle

    auth = request.headers.get("authorization")
    scheme, param = get_authorization_scheme_param(auth or "")
    if (
        scheme.lower() != "bearer"
        or not param
        or not param.isascii()
        or not TOKEN
        or not TOKEN.isascii()
        or not hmac.compare_digest(param, TOKEN)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

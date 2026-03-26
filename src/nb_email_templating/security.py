"""Auth (token + session), CSRF, and template name validation."""

import re
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, Header, Query, Request, status
from fastapi.responses import RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import AppConfig

# Template name allowed chars (no path traversal)
TEMPLATE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.html\.j2$")


def validate_template_name(name: str) -> bool:
    return bool(name and TEMPLATE_NAME_RE.match(name))


def resolve_template_path(templates_dir: Path, name: str) -> Path | None:
    """Resolve template file path; return None if outside templates_dir."""
    if not validate_template_name(name):
        return None
    resolved = (templates_dir / name).resolve()
    try:
        resolved.relative_to(templates_dir.resolve())
    except ValueError:
        return None
    return resolved if resolved.exists() else None


async def require_webhook_token(
    token: Annotated[str | None, Query(alias="token")] = None,
    config: AppConfig = None,
) -> None:
    """Validate ?token= for webhook; raise 401 if missing or wrong."""
    if config is None:
        from .main import get_config
        config = get_config()
    if not token or token != config.auth.webhook_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


async def get_webhook_token_dep(
    request: Request,
    token: Annotated[str | None, Query(alias="token")] = None,
):
    """Dependency that gets config from app state and validates token."""
    from fastapi import HTTPException
    config = request.app.state.config
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")
    if not token or token != config.auth.webhook_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


async def get_session_id(
    request: Request,
    cookie_name: str = "nb_email_session",
) -> str | None:
    return request.cookies.get(cookie_name)


async def require_auth(
    request: Request,
    token: Annotated[str | None, Query(alias="token")] = None,
    session_id: Annotated[str | None, Cookie()] = None,
) -> None:
    """Validate ?token= OR valid session cookie for dashboard."""
    from fastapi import HTTPException
    config = request.app.state.config
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")
    if token and token == config.auth.webhook_token:
        return
    # Session store: in-memory for now (app.state.sessions)
    sessions = getattr(request.app.state, "sessions", None) or {}
    if session_id and sessions.get(session_id):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


async def require_auth_csrf(
    request: Request,
    token: Annotated[str | None, Query(alias="token")] = None,
    session_id: Annotated[str | None, Cookie()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    """Validate auth and CSRF token for mutations."""
    await require_auth(request, token, session_id)
    # CSRF: from header or form body
    csrf = x_csrf_token or (await request.form()).get("csrf_token") if request.method in ("POST", "PUT", "DELETE") else None
    if not csrf:
        body = await request.body()
        if body:
            try:
                import json
                data = json.loads(body)
                csrf = data.get("csrf_token")
            except Exception:
                pass
    sessions = getattr(request.app.state, "sessions", None) or {}
    session_id_val = request.cookies.get(request.app.state.config.auth.session_cookie_name, session_id)
    expected = sessions.get(session_id_val, {}).get("csrf_token") if session_id_val else None
    if not expected or csrf != expected:
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def create_session_and_cookie(config: AppConfig) -> tuple[str, str]:
    """Create new session id and csrf token; return (session_id, csrf_token)."""
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    return session_id, csrf_token


def set_session_cookie_response(response: Response, config: AppConfig, session_id: str, csrf_token: str) -> None:
    """Set HttpOnly session cookie and store session in app state (caller must attach)."""
    response.set_cookie(
        key=config.auth.session_cookie_name,
        value=session_id,
        max_age=config.auth.session_max_age_seconds,
        httponly=True,
        samesite="lax",
    )


class RedactTokenMiddleware(BaseHTTPMiddleware):
    """Redact ?token= from request URL in logs (use scope path + query with token stripped)."""

    async def dispatch(self, request: Request, call_next):
        # Strip token from query for logging
        query = request.scope.get("query_string", b"").decode()
        if "token=" in query:
            import urllib.parse
            qs = urllib.parse.parse_qs(query)
            if "token" in qs:
                qs["token"] = ["[REDACTED]"]
            request.scope["_redacted_query"] = urllib.parse.urlencode(qs, doseq=True)
        return await call_next(request)

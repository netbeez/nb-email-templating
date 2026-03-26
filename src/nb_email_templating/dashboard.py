"""Dashboard routes: overview, events, config view, retry. Auth via ?token= or session."""

import asyncio
import json
import secrets
from pathlib import Path
from urllib.parse import urlencode, urljoin

from fastapi import APIRouter, Request, Depends, HTTPException, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from .database import Event, Delivery
from .security import validate_template_name

router = APIRouter()

import os as _os
DASHBOARD_TEMPLATES_DIR = Path(_os.environ.get("DASHBOARD_TEMPLATES_DIR") or str(Path(__file__).parent.parent.parent / "dashboard_templates"))


def _get_jinja_env():
    from jinja2 import Environment, FileSystemLoader
    return Environment(loader=FileSystemLoader(str(DASHBOARD_TEMPLATES_DIR)))


def _beezkeeper_webhook_url(request: Request, config) -> str:
    """Full POST /webhook URL with token for NetBeez Beezkeeper (JSON:API)."""
    public = (getattr(config.server, "public_base_url", None) or "").strip()
    if public:
        base = public.rstrip("/") + "/"
    else:
        base = str(request.base_url)
    path = urljoin(base, "webhook")
    token = (config.auth.webhook_token or "").strip()
    return f"{path}?{urlencode({'token': token})}"


def _redact_config(cfg) -> dict:
    """Return config dict with secrets redacted."""
    d = cfg.model_dump() if hasattr(cfg, "model_dump") else {}
    if "auth" in d and isinstance(d["auth"], dict):
        d["auth"] = {**d["auth"], "webhook_token": "[REDACTED]"}
    if "smtp" in d and isinstance(d["smtp"], dict):
        d["smtp"] = {**d["smtp"], "username": "[REDACTED]", "password": "[REDACTED]"}
    return d


async def _require_auth(request: Request):
    token = request.query_params.get("token")
    config = getattr(request.app.state, "config", None)
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")
    if token and token == config.auth.webhook_token:
        return True
    session_id = request.cookies.get(config.auth.session_cookie_name)
    sessions = getattr(request.app.state, "sessions", {}) or {}
    if session_id and sessions.get(session_id):
        return True
    raise HTTPException(status_code=401, detail="Authentication required")


async def _require_auth_csrf(request: Request, csrf: str = Query(None), form_csrf: str = None):
    await _require_auth(request)
    config = request.app.state.config
    session_id = request.cookies.get(config.auth.session_cookie_name)
    sessions = getattr(request.app.state, "sessions", {}) or {}
    expected = sessions.get(session_id, {}).get("csrf_token") if session_id else None
    token = request.query_params.get("token")
    if token and token == config.auth.webhook_token:
        return True  # Token auth bypasses CSRF
    csrf_val = csrf or form_csrf or request.headers.get("X-CSRF-Token")
    if not expected or csrf_val != expected:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return True


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, _: bool = Depends(_require_auth)):
    env = _get_jinja_env()
    config = request.app.state.config
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(
            select(Event).order_by(Event.created_at.desc()).limit(20)
        )
        events = result.scalars().all()
    templates_config = {k: v.model_dump() if hasattr(v, "model_dump") else v for k, v in (config.templates or {}).items()}
    template = env.get_template("index.html.j2")
    html = template.render(
        config=config,
        templates_config=templates_config,
        events=events,
        beezkeeper_webhook_url=_beezkeeper_webhook_url(request, config),
    )
    return HTMLResponse(html)


@router.get("/events", response_class=HTMLResponse)
async def events_list(
    request: Request,
    _: bool = Depends(_require_auth),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    env = _get_jinja_env()
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(
            select(Event)
            .options(selectinload(Event.deliveries))
            .order_by(Event.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        events = result.scalars().all()
    template = env.get_template("events.html.j2")
    html = template.render(events=events, page=page, per_page=per_page)
    return HTMLResponse(html)


@router.post("/events/{event_id:int}/retry")
async def retry_event(
    request: Request,
    event_id: int,
    _: bool = Depends(_require_auth),
):
    from .webhook import _deliver_event
    from .parser import parse_webhook_payload
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        result = await session.execute(select(Event).where(Event.id == event_id))
        ev = result.scalar_one_or_none()
        if not ev:
            raise HTTPException(status_code=404, detail="Event not found")
        if ev.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed events can be retried")
        await session.execute(update(Event).where(Event.id == event_id).values(status="received"))
        await session.commit()
    config = request.app.state.config
    parsed = parse_webhook_payload(json.loads(ev.payload))
    task = asyncio.create_task(
        _deliver_event(
            ev.event_id,
            ev.id,
            parsed,
            config,
            request.app.state.renderer,
            request.app.state.smtp_semaphore,
            session_factory,
            request.app.state.delivery_tasks,
        )
    )
    request.app.state.delivery_tasks.add(task)
    task.add_done_callback(request.app.state.delivery_tasks.discard)
    return RedirectResponse(url="/events", status_code=303)


@router.get("/config", response_class=HTMLResponse)
async def config_view(request: Request, _: bool = Depends(_require_auth)):
    env = _get_jinja_env()
    config = request.app.state.config
    config_str = json.dumps(_redact_config(config), indent=2)
    template = env.get_template("config_view.html.j2")
    html = template.render(config_redacted=config_str)
    return HTMLResponse(html)


@router.get("/login")
async def login(request: Request, token: str | None = Query(None), error: int | None = Query(None)):
    """Show login form, or set session cookie when token is provided."""
    env = _get_jinja_env()
    config = getattr(request.app.state, "config", None)
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")

    # Backward compatibility for existing token-based login URLs.
    if token is None:
        template = env.get_template("login.html.j2")
        return HTMLResponse(template.render(error=bool(error)))
    if token != config.auth.webhook_token:
        template = env.get_template("login.html.j2")
        return HTMLResponse(template.render(error=True), status_code=401)

    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    sessions = getattr(request.app.state, "sessions", None)
    if sessions is None:
        request.app.state.sessions = {}
        sessions = request.app.state.sessions
    sessions[session_id] = {"csrf_token": csrf_token}
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=config.auth.session_cookie_name,
        value=session_id,
        max_age=config.auth.session_max_age_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/login")
async def login_submit(request: Request, password: str = Form("")):
    """Authenticate user from form password and set session cookie."""
    config = getattr(request.app.state, "config", None)
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")
    if password != config.auth.webhook_token:
        return RedirectResponse(url="/login?error=1", status_code=303)

    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    sessions = getattr(request.app.state, "sessions", None)
    if sessions is None:
        request.app.state.sessions = {}
        sessions = request.app.state.sessions
    sessions[session_id] = {"csrf_token": csrf_token}

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=config.auth.session_cookie_name,
        value=session_id,
        max_age=config.auth.session_max_age_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    """Clear current auth session and redirect to login page."""
    config = getattr(request.app.state, "config", None)
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")

    session_id = request.cookies.get(config.auth.session_cookie_name)
    sessions = getattr(request.app.state, "sessions", {}) or {}
    if session_id:
        sessions.pop(session_id, None)

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=config.auth.session_cookie_name)
    return response

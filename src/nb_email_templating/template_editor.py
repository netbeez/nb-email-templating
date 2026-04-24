"""Template CRUD API: list, get, save (with syntax check), preview. Path validation."""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError
import yaml

from .config import load_config
from .dashboard import get_dashboard_jinja_env
from .renderer import TemplateRenderer
from .security import validate_template_name

router = APIRouter()


def _templates_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "email_templates_dir", "/app/email_templates"))


def _find_event_type(config: Any, filename: str) -> str | None:
    templates = getattr(config, "templates", {}) or {}
    for event_type, entry in templates.items():
        if getattr(entry, "file", None) == filename:
            return event_type
    return None


def _update_config_template(config_path: Path, event_type: str, updates: dict[str, Any]) -> None:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    templates = raw.get("templates")
    if not isinstance(templates, dict):
        raise HTTPException(status_code=400, detail="Config does not contain a templates mapping")
    event = templates.get(event_type)
    if not isinstance(event, dict):
        raise HTTPException(status_code=404, detail=f"Event type {event_type!r} not found in config")
    event.update(updates)

    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    os.replace(tmp, config_path)


def _update_all_config_templates(config_path: Path, updates: dict[str, Any]) -> list[str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    templates = raw.get("templates")
    if not isinstance(templates, dict):
        raise HTTPException(status_code=400, detail="Config does not contain a templates mapping")
    applied_to: list[str] = []
    for event_type, event in templates.items():
        if not isinstance(event, dict):
            continue
        event.update(updates)
        applied_to.append(event_type)

    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    os.replace(tmp, config_path)
    return applied_to


def _validate_recipients(recipients: Any) -> dict[str, list[str]]:
    if not isinstance(recipients, dict):
        raise HTTPException(status_code=400, detail="recipients must be an object")
    normalized: dict[str, list[str]] = {}
    for field in ("to", "cc", "bcc"):
        value = recipients.get(field, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise HTTPException(status_code=400, detail=f"recipients.{field} must be a list")
        items: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise HTTPException(status_code=400, detail=f"recipients.{field} entries must be non-empty strings")
            items.append(item.strip())
        normalized[field] = items
    return normalized


def _reload_config_and_renderer(request: Request, config_path: Path) -> None:
    new_config = load_config(config_path)
    templates_dir = _templates_dir(request)
    request.app.state.config = new_config
    request.app.state.renderer = TemplateRenderer(
        templates_dir,
        render_timeout_seconds=new_config.rendering.template_render_timeout_seconds,
        template_config={k: v for k, v in new_config.templates.items()},
    )


async def _require_auth(request: Request) -> bool:
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


@router.get("/templates", response_class=HTMLResponse)
async def template_editor_page(request: Request, _=Depends(_require_auth)):
    templates_dir = _templates_dir(request)
    names = [f.name for f in templates_dir.glob("*.html.j2")] if templates_dir.exists() else []
    env = get_dashboard_jinja_env()
    template = env.get_template("template_editor.html.j2")
    return HTMLResponse(template.render(template_names=names))


@router.get("/templates/legend", response_class=HTMLResponse)
async def template_legend_page(request: Request, _=Depends(_require_auth)):
    env = get_dashboard_jinja_env()
    template = env.get_template("template_legend.html.j2")
    return HTMLResponse(template.render(event_type=None))


@router.get("/templates/{name}", response_class=HTMLResponse)
async def template_edit_page(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir(request)
    path = (templates_dir / name).resolve()
    if not str(path).startswith(str(templates_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    content = path.read_text(encoding="utf-8")
    config = getattr(request.app.state, "config", None)
    event_type = _find_event_type(config, name) if config else None
    subject = None
    recipients = {"to": [], "cc": [], "bcc": []}
    if config and event_type and event_type in config.templates:
        subject = config.templates[event_type].subject
        recipients_cfg = config.templates[event_type].recipients
        if hasattr(recipients_cfg, "model_dump"):
            recipients = recipients_cfg.model_dump()
        elif isinstance(recipients_cfg, dict):
            recipients = recipients_cfg
    env = get_dashboard_jinja_env()
    template = env.get_template("template_edit.html.j2")
    return HTMLResponse(template.render(name=name, content=content, event_type=event_type, subject=subject, recipients=recipients))


@router.get("/api/templates")
async def list_templates(request: Request, _=Depends(_require_auth)):
    templates_dir = _templates_dir(request)
    if not templates_dir.exists():
        return {"templates": []}
    files = [f.name for f in templates_dir.glob("*.html.j2")]
    return {"templates": files}


@router.get("/api/templates/{name}")
async def get_template(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir(request)
    path = (templates_dir / name).resolve()
    if not str(path).startswith(str(templates_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    config = getattr(request.app.state, "config", None)
    event_type = _find_event_type(config, name) if config else None
    subject = None
    recipients = {"to": [], "cc": [], "bcc": []}
    if config and event_type and event_type in config.templates:
        subject = config.templates[event_type].subject
        recipients_cfg = config.templates[event_type].recipients
        if hasattr(recipients_cfg, "model_dump"):
            recipients = recipients_cfg.model_dump()
        elif isinstance(recipients_cfg, dict):
            recipients = recipients_cfg
    return {
        "name": name,
        "content": path.read_text(encoding="utf-8"),
        "event_type": event_type,
        "subject": subject,
        "recipients": recipients,
    }


@router.put("/api/templates/{name}")
async def save_template(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    templates_dir = _templates_dir(request)
    path = (templates_dir / name).resolve()
    if not str(path).startswith(str(templates_dir.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")
    body = await request.json()
    content = body.get("content", "")
    subject = body.get("subject")
    recipients = body.get("recipients")
    env = Environment()
    try:
        env.parse(content)
    except TemplateSyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Invalid Jinja2 syntax: {e}")
    if subject is not None:
        try:
            env.parse(subject)
        except TemplateSyntaxError as e:
            raise HTTPException(status_code=400, detail=f"Invalid subject Jinja2 syntax: {e}")
    normalized_recipients = None
    if recipients is not None:
        normalized_recipients = _validate_recipients(recipients)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)

    if subject is not None or normalized_recipients is not None:
        config = getattr(request.app.state, "config", None)
        if not config:
            raise HTTPException(status_code=500, detail="Config not loaded")
        event_type = _find_event_type(config, name)
        if event_type:
            config_path = Path(getattr(request.app.state, "config_path", "/app/config/config.yaml"))
            lock = getattr(request.app.state, "reload_lock", None)
            if not lock:
                raise HTTPException(status_code=500, detail="Reload lock not available")
            async with lock:
                updates: dict[str, Any] = {}
                if subject is not None:
                    updates["subject"] = subject
                if normalized_recipients is not None:
                    updates["recipients"] = normalized_recipients
                _update_config_template(config_path, event_type, updates)
                _reload_config_and_renderer(request, config_path)

    return {"ok": True}


@router.post("/api/templates/{name}/apply-recipients")
async def apply_recipients_to_all(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    body = await request.json()
    recipients = _validate_recipients(body.get("recipients"))
    config_path = Path(getattr(request.app.state, "config_path", "/app/config/config.yaml"))
    lock = getattr(request.app.state, "reload_lock", None)
    if not lock:
        raise HTTPException(status_code=500, detail="Reload lock not available")
    async with lock:
        applied_to = _update_all_config_templates(config_path, {"recipients": recipients})
        _reload_config_and_renderer(request, config_path)
    return {"ok": True, "applied_to": applied_to}


@router.post("/api/templates/{event_type}/toggle-active")
async def toggle_template_active(request: Request, event_type: str, _=Depends(_require_auth)):
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    config = getattr(request.app.state, "config", None)
    if not config:
        raise HTTPException(status_code=500, detail="Config not loaded")
    template_entry = (config.templates or {}).get(event_type)
    if not template_entry:
        raise HTTPException(status_code=404, detail=f"Event type {event_type!r} not found in config")

    if "active" in body:
        if not isinstance(body["active"], bool):
            raise HTTPException(status_code=400, detail="active must be a boolean")
        active = body["active"]
    else:
        active = not bool(getattr(template_entry, "active", True))

    config_path = Path(getattr(request.app.state, "config_path", "/app/config/config.yaml"))
    lock = getattr(request.app.state, "reload_lock", None)
    if not lock:
        raise HTTPException(status_code=500, detail="Reload lock not available")
    async with lock:
        _update_config_template(config_path, event_type, {"active": active})
        _reload_config_and_renderer(request, config_path)
    return {"ok": True, "active": active}


@router.post("/api/templates/{name}/preview")
async def preview_template(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    body = await request.json() or {}
    payload = body.get("payload") or {}
    renderer = getattr(request.app.state, "renderer", None)
    if not renderer:
        raise HTTPException(status_code=500, detail="Renderer not available")
    from .context import build_render_context
    from .parser import parse_webhook_payload
    try:
        parsed = parse_webhook_payload(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    cfg = request.app.state.config
    context = build_render_context(parsed, cfg.template_context)
    html, err = await renderer.render_body(context["event_type"], context)
    subject = renderer.render_subject(context["event_type"], context)
    return {"html": html or "", "subject": subject, "error": err}

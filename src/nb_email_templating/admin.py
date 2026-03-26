"""Admin: config/template reload with validate-before-apply and read-write lock."""

from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException

from .config import load_config

router = APIRouter()


def _require_auth(request: Request):
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


def _require_csrf(request: Request):
    csrf = request.headers.get("X-CSRF-Token") or (request.query_params.get("csrf_token"))
    config = request.app.state.config
    session_id = request.cookies.get(config.auth.session_cookie_name)
    sessions = getattr(request.app.state, "sessions", {}) or {}
    expected = sessions.get(session_id, {}).get("csrf_token") if session_id else None
    if config.auth.webhook_token and request.query_params.get("token") == config.auth.webhook_token:
        return True
    if not expected or csrf != expected:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return True


@router.post("/admin/reload")
async def admin_reload(request: Request, _=Depends(_require_auth), __=Depends(_require_csrf)):
    """Hot-reload config and templates. Validates before applying. Uses reload lock."""
    config_path = getattr(request.app.state, "config_path", "/app/config/config.yaml")
    lock = getattr(request.app.state, "reload_lock", None)
    if not lock:
        raise HTTPException(status_code=500, detail="Reload lock not available")
    async with lock:
        try:
            new_config = load_config(config_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Config validation failed: {e}")
        templates_dir = getattr(request.app.state, "email_templates_dir", "/app/email_templates")
        if not Path(templates_dir).exists():
            raise HTTPException(status_code=400, detail="Template directory not found")
        request.app.state.config = new_config
        from .renderer import TemplateRenderer
        request.app.state.renderer = TemplateRenderer(
            templates_dir,
            render_timeout_seconds=new_config.rendering.template_render_timeout_seconds,
            template_config={k: v for k, v in new_config.templates.items()},
        )
    return {"ok": True}

"""Test endpoints: SMTP test, render preview. Rate limited per session."""

import json
import time
from collections import defaultdict
from html import escape

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .mailer import send_email
from .parser import parse_webhook_payload
from .context import build_render_context

router = APIRouter()

# Rate limit: sends per minute per session (in-memory)
_send_times: dict[str, list[float]] = defaultdict(list)


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


def _check_rate_limit(request: Request) -> None:
    config = request.app.state.config
    limit = config.test_tools.rate_limit_per_minute
    key = request.cookies.get(config.auth.session_cookie_name) or request.client.host if request.client else "anon"
    now = time.time()
    _send_times[key] = [t for t in _send_times[key] if now - t < 60]
    if len(_send_times[key]) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _send_times[key].append(now)


def _render_preview_page(subject: str, html: str | None, error: str | None) -> HTMLResponse:
    subject_escaped = escape(subject or "(no subject)")
    if error:
        body = (
            '<p class="status-error" style="margin:0 0 8px 0;font-weight:600;">Render error</p>'
            f"<pre style=\"white-space:pre-wrap;\">{escape(error)}</pre>"
        )
    else:
        srcdoc = escape(html or "<p>(empty preview)</p>")
        body = (
            '<iframe title="Email preview" '
            'style="width:100%;height:80vh;border:0;border-radius:10px;background:#fff;" '
            f'srcdoc="{srcdoc}"></iframe>'
        )

    page = (
        "<!doctype html>"
        "<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>Preview - {subject_escaped}</title>"
        "<link rel=\"stylesheet\" href=\"/static/style.css\">"
        "</head><body>"
        "<main class=\"app-main container\">"
        "<section class=\"panel\">"
        "<p><a href=\"/test\">&larr; Back to test tools</a></p>"
        f"<h2>Subject: {subject_escaped}</h2>"
        f"{body}</section>"
        "</main>"
        "</body></html>"
    )
    return HTMLResponse(content=page)


@router.get("/test", response_class=HTMLResponse)
async def test_tools_page(request: Request, _=Depends(_require_auth)):
    from jinja2 import Environment, FileSystemLoader
    import os as _os
    env = Environment(loader=FileSystemLoader(_os.environ.get("DASHBOARD_TEMPLATES_DIR") or str(__import__("pathlib").Path(__file__).parent.parent.parent / "dashboard_templates")))
    return HTMLResponse(env.get_template("test_tools.html.j2").render())


@router.post("/test/smtp")
async def test_smtp(request: Request, _=Depends(_require_auth)):
    _check_rate_limit(request)
    form = await request.form()
    to_email = form.get("to")
    if not to_email:
        raise HTTPException(status_code=400, detail="Missing 'to' address")
    config = request.app.state.config
    success, attempts, err = await send_email(
        config.smtp,
        to=[to_email],
        subject="[NetBeez] Test email",
        body_html="<p>This is a test email from nb-email-templating.</p>",
        max_attempts=2,
    )
    if success:
        return {"ok": True, "attempts": attempts}
    return JSONResponse(status_code=502, content={"ok": False, "error": err, "attempts": attempts})


@router.post("/test/render")
async def test_render(request: Request, _=Depends(_require_auth)):
    form = await request.form()
    event_type = form.get("event_type", "ALERT_OPEN")
    payload_str = form.get("payload", "{}")
    action = form.get("action", "preview")
    try:
        payload = json.loads(payload_str) if payload_str else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not payload.get("data"):
        payload = {"data": {"id": "test-1", "type": "alert", "attributes": {"event_type": event_type, "message": "Test message"}}}
    try:
        parsed = parse_webhook_payload(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    renderer = request.app.state.renderer
    cfg = request.app.state.config
    context = build_render_context(parsed, cfg.template_context)
    html, err = await renderer.render_body(context["event_type"], context)
    subject = renderer.render_subject(context["event_type"], context)
    if action == "send":
        _check_rate_limit(request)
        to_email = form.get("to")
        if not to_email:
            raise HTTPException(status_code=400, detail="Missing 'to' for send")
        success, attempts, send_err = await send_email(
            request.app.state.config.smtp,
            to=[to_email],
            subject=subject,
            body_html=html or "<p>Render failed</p>",
            max_attempts=2,
        )
        if not success:
            return JSONResponse(status_code=502, content={"ok": False, "error": send_err})
        return {"ok": True, "attempts": attempts}
    return _render_preview_page(subject=subject, html=html, error=err)

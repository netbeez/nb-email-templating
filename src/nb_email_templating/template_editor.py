"""Template CRUD API: list, get, save (with syntax check), preview. Path validation."""

import os
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse

from .security import validate_template_name

router = APIRouter()


def _templates_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "email_templates_dir", "/app/email_templates"))


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
    from jinja2 import Environment, FileSystemLoader
    templates_dir = _templates_dir(request)
    names = [f.name for f in templates_dir.glob("*.html.j2")] if templates_dir.exists() else []
    env = Environment(loader=FileSystemLoader(os.environ.get("DASHBOARD_TEMPLATES_DIR") or str(Path(__file__).parent.parent.parent / "dashboard_templates")))
    template = env.get_template("template_editor.html.j2")
    return HTMLResponse(template.render(template_names=names))


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
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(os.environ.get("DASHBOARD_TEMPLATES_DIR") or str(Path(__file__).parent.parent.parent / "dashboard_templates")))
    template = env.get_template("template_edit.html.j2")
    return HTMLResponse(template.render(name=name, content=content))


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
    return {"name": name, "content": path.read_text(encoding="utf-8")}


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
    from jinja2 import Environment
    env = Environment()
    try:
        env.parse(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Jinja2 syntax: {e}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True}


@router.post("/api/templates/{name}/preview")
async def preview_template(request: Request, name: str, _=Depends(_require_auth)):
    if not validate_template_name(name):
        raise HTTPException(status_code=400, detail="Invalid template name")
    body = await request.json() or {}
    payload = body.get("payload") or {}
    renderer = getattr(request.app.state, "renderer", None)
    if not renderer:
        raise HTTPException(status_code=500, detail="Renderer not available")
    from .parser import parse_webhook_payload
    try:
        parsed = parse_webhook_payload(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    context = {
        "event_type": parsed.get("event_type", "_fallback"),
        "event_id": parsed.get("event_id"),
        "data_type": parsed.get("data_type"),
        "attributes": parsed.get("attributes") or {},
        "alerts": parsed.get("alerts") or [],
    }
    html, err = await renderer.render_body(context["event_type"], context)
    return {"html": html or "", "error": err}

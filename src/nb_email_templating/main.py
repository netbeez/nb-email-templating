"""FastAPI app: lifespan, health, graceful shutdown, startup recovery."""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

from .config import AppConfig, load_config
from .database import Event, get_engine, get_session_factory, init_db
from .logger import setup_logging
from .renderer import TemplateRenderer
from .mailer import get_smtp_semaphore
from .webhook import router as webhook_router, _deliver_event
from .parser import parse_webhook_payload
from . import dashboard, template_editor, testing, admin

# Config path from env or default
_root = Path(__file__).parent.parent.parent
CONFIG_PATH = os.environ.get("CONFIG_PATH") or str(_root / "config" / "config.yaml")
if not Path(CONFIG_PATH).exists():
    CONFIG_PATH = str(_root / "config" / "config.example.yaml")
TEMPLATES_DIR = os.environ.get("EMAIL_TEMPLATES_DIR") or str(_root / "email_templates")
DATA_DIR = os.environ.get("DATA_DIR", str(_root / "data"))
JINJA2_BYTECODE_CACHE_DIR = os.environ.get(
    "JINJA2_BYTECODE_CACHE_DIR",
    str(Path(DATA_DIR) / ".jinja2_cache"),
)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{Path(DATA_DIR).resolve()}/events.db")

_app_config: AppConfig | None = None


def get_config() -> AppConfig:
    if _app_config is None:
        raise RuntimeError("Config not loaded")
    return _app_config


app = FastAPI(title="nb-email-templating", version="0.1.0")
app.include_router(webhook_router, tags=["webhook"])
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(template_editor.router, tags=["templates"])
app.include_router(testing.router, tags=["testing"])
app.include_router(admin.router, tags=["admin"])

STATIC_DIR = Path(os.environ.get("STATIC_DIR") or str(Path(__file__).parent.parent.parent / "static"))
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return 400 for malformed JSON / validation errors instead of 422."""
    return JSONResponse(status_code=400, content={"error": "Invalid request", "detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Redirect browser auth failures to login; keep API errors as JSON."""
    browser_paths = ("/api/", "/webhook", "/admin/", "/health", "/login")
    if exc.status_code == 401 and not request.url.path.startswith(browser_paths):
        return RedirectResponse(url="/login", status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.on_event("startup")
async def startup():
    global _app_config
    try:
        _app_config = load_config(CONFIG_PATH)
    except FileNotFoundError:
        example = _root / "config" / "config.example.yaml"
        if example.exists():
            _app_config = load_config(str(example))
        else:
            raise
    setup_logging(
        _app_config.logging.path,
        max_bytes=_app_config.logging.max_bytes,
        backup_count=_app_config.logging.backup_count,
        level=_app_config.logging.level,
    )
    Path(_app_config.logging.path).mkdir(parents=True, exist_ok=True)
    Path(TEMPLATES_DIR).mkdir(parents=True, exist_ok=True)
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(JINJA2_BYTECODE_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    engine = get_engine(DATABASE_URL)
    await init_db(engine)
    session_factory = get_session_factory(engine)
    app.state.config = _app_config
    app.state.session_factory = session_factory
    app.state.engine = engine
    app.state.smtp_semaphore = get_smtp_semaphore(_app_config)
    app.state.delivery_tasks = set()
    template_config = {k: v for k, v in _app_config.templates.items()}
    app.state.renderer = TemplateRenderer(
        TEMPLATES_DIR,
        bytecode_cache_dir=JINJA2_BYTECODE_CACHE_DIR,
        render_timeout_seconds=_app_config.rendering.template_render_timeout_seconds,
        template_config=template_config,
    )
    app.state.jinja2_bytecode_cache_dir = JINJA2_BYTECODE_CACHE_DIR
    app.state.sessions = {}
    app.state.reload_lock = asyncio.Lock()
    app.state.email_templates_dir = TEMPLATES_DIR
    app.state.config_path = CONFIG_PATH

    # Startup recovery: re-queue received and stuck processing events
    from sqlalchemy import select
    recovery_seconds = _app_config.retry.recovery_timeout_seconds
    cutoff = datetime.utcnow() - timedelta(seconds=recovery_seconds)
    async with session_factory() as session:
        result = await session.execute(
            select(Event).where(
                (Event.status == "received") |
                ((Event.status == "processing") & (Event.updated_at < cutoff))
            )
        )
        events = result.scalars().all()
    for ev in events:
        try:
            payload = json.loads(ev.payload)
            parsed = parse_webhook_payload(payload)
            task = asyncio.create_task(
                _deliver_event(
                    ev.event_id,
                    ev.id,
                    parsed,
                    _app_config,
                    app.state.renderer,
                    app.state.smtp_semaphore,
                    session_factory,
                    app.state.delivery_tasks,
                )
            )
            app.state.delivery_tasks.add(task)
            task.add_done_callback(app.state.delivery_tasks.discard)
        except Exception:
            pass


@app.on_event("shutdown")
async def shutdown():
    cfg = getattr(app.state, "config", None)
    timeout = cfg.server.shutdown_timeout_seconds if cfg else 30
    tasks = getattr(app.state, "delivery_tasks", set())
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
    engine = getattr(app.state, "engine", None)
    if engine:
        await engine.dispose()


@app.get("/health")
async def health():
    """Health check: DB writable, log path writable. SMTP status cached."""
    cfg = getattr(app.state, "config", None)
    if not cfg:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": "config not loaded"})
    checks = {}
    try:
        async with app.state.session_factory() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = str(e)
    log_path = Path(cfg.logging.path)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
        (log_path / ".health").touch()
        checks["logs"] = "ok"
    except Exception as e:
        checks["logs"] = str(e)
    checks["smtp_checked_at"] = getattr(app.state, "smtp_checked_at", None)
    healthy = checks.get("database") == "ok" and checks.get("logs") == "ok"
    return {"status": "healthy" if healthy else "degraded", "checks": checks}


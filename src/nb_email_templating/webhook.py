"""POST /webhook endpoint: auth, size limit, parse, dedup, persist, background delivery."""

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .config import AppConfig
from .database import Event, get_session_factory
from .dedup import try_insert_event
from .parser import parse_webhook_payload
from .renderer import TemplateRenderer
from .mailer import send_email
from .context import build_render_context

logger = logging.getLogger(__name__)
router = APIRouter()

STATUS_PROCESSING = "processing"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"


async def _deliver_event(
    event_id: str,
    db_id: int,
    parsed: dict[str, Any],
    config: AppConfig,
    renderer: TemplateRenderer,
    semaphore: asyncio.Semaphore,
    session_factory,
    delivery_tasks: set,
) -> None:
    """Background task: update to processing, render, send, record delivery."""
    request_id = str(uuid.uuid4())
    try:
        async with session_factory() as session:
            from sqlalchemy import select, update
            from .database import Delivery

            await session.execute(update(Event).where(Event.id == db_id).values(status=STATUS_PROCESSING))
            await session.commit()

        event_type = parsed.get("event_type") or "_fallback"
        context = build_render_context(parsed, config.template_context)
        subject = renderer.render_subject(event_type, context)
        body_html, render_error = await renderer.render_body(event_type, context)
        if body_html is None or (not body_html and render_error):
            async with session_factory() as session:
                await session.execute(update(Event).where(Event.id == db_id).values(status=STATUS_FAILED))
                del_rec = Delivery(event_id=db_id, success=False, attempts=0, error_message=render_error or "Render failed")
                session.add(del_rec)
                await session.commit()
            return

        template_config = config.templates.get(event_type) or config.templates.get("_fallback")
        if not template_config or not template_config.active:
            async with session_factory() as session:
                await session.execute(update(Event).where(Event.id == db_id).values(status=STATUS_FAILED))
                session.add(Delivery(event_id=db_id, success=False, attempts=0, error_message="Template inactive"))
                await session.commit()
            return

        recipients = template_config.recipients
        to_list = recipients.to or []
        if not to_list:
            to_list = ["ops@example.com"]
        success, attempts, err = await send_email(
            config.smtp,
            to=to_list,
            cc=recipients.cc or [],
            bcc=recipients.bcc or [],
            subject=subject,
            body_html=body_html,
            max_attempts=config.retry.max_attempts,
            backoff_base_seconds=config.retry.backoff_base_seconds,
            backoff_max_seconds=config.retry.backoff_max_seconds,
            semaphore=semaphore,
        )
        async with session_factory() as session:
            from .database import Delivery
            await session.execute(
                update(Event).where(Event.id == db_id).values(status=STATUS_DELIVERED if success else STATUS_FAILED)
            )
            session.add(Delivery(event_id=db_id, success=success, attempts=attempts, error_message=err))
            await session.commit()
    except Exception as e:
        logger.exception("Delivery failed for event %s", event_id, extra={"request_id": request_id})
        async with session_factory() as session:
            from sqlalchemy import update
            from .database import Delivery
            await session.execute(update(Event).where(Event.id == db_id).values(status=STATUS_FAILED))
            session.add(Delivery(event_id=db_id, success=False, attempts=0, error_message=str(e)))
            await session.commit()
    finally:
        pass


@router.post("/webhook")
async def webhook_post(request: Request) -> Response:
    """Accept JSON:API webhook; validate auth, parse, dedup, persist, spawn delivery task."""
    config: AppConfig = request.app.state.config
    if not config:
        return JSONResponse(status_code=500, content={"error": "Config not loaded"})

    token = request.query_params.get("token")
    if not token or token != config.auth.webhook_token:
        return JSONResponse(status_code=401, content={"error": "Invalid or missing token"})

    max_size = config.server.max_request_size
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_size:
        return JSONResponse(status_code=413, content={"error": "Payload too large"})

    body_bytes = await request.body()
    if len(body_bytes) > max_size:
        return JSONResponse(status_code=413, content={"error": "Payload too large"})

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON", "detail": str(e)})

    # NetBeez dashboard connectivity checks may POST JSON without a `data` member.
    if "data" not in payload or payload.get("data") is None:
        logger.info("Webhook accepted with no 'data' (connectivity test); skipping persist and delivery")
        return Response(status_code=200, content=b"")

    try:
        parsed = parse_webhook_payload(payload)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": "Invalid payload", "detail": str(e)})

    event_id = parsed["event_id"]
    event_type = parsed["event_type"]
    request_id = str(uuid.uuid4())

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        db_id = await try_insert_event(session, event_id, payload, event_type)
    if db_id is None:
        return Response(status_code=200, content=b"")  # Duplicate, accept but do not send

    renderer = request.app.state.renderer
    semaphore = request.app.state.smtp_semaphore
    delivery_tasks = request.app.state.delivery_tasks
    task = asyncio.create_task(
        _deliver_event(
            event_id,
            db_id,
            parsed,
            config,
            renderer,
            semaphore,
            session_factory,
            delivery_tasks,
        )
    )
    delivery_tasks.add(task)
    task.add_done_callback(delivery_tasks.discard)
    return Response(status_code=200, content=b"")

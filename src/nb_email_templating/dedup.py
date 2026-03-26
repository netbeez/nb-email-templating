"""Deduplication by event_id with atomic INSERT OR IGNORE; data retention cleanup."""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Delivery, Event

STATUS_RECEIVED = "received"


async def try_insert_event(
    session: AsyncSession,
    event_id: str,
    payload: dict[str, Any],
    event_type: str,
) -> int | None:
    """
    Atomic INSERT OR IGNORE. Returns inserted Event.id if new row, None if duplicate.
    """
    payload_json = json.dumps(payload)
    stmt = insert(Event).values(
        event_id=event_id,
        status=STATUS_RECEIVED,
        payload=payload_json,
        event_type=event_type,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
    result = await session.execute(stmt)
    await session.commit()
    if result.rowcount and result.rowcount > 0:
        from sqlalchemy import select
        r = await session.execute(select(Event.id).where(Event.event_id == event_id).limit(1))
        return r.scalar_one_or_none()
    return None


async def get_events_for_retention_cleanup(
    session: AsyncSession,
    older_than_days: int,
) -> list[Event]:
    """Return events (and their delivery records) older than N days for pruning."""
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    result = await session.execute(
        select(Event).where(Event.created_at < cutoff)
    )
    return list(result.scalars().all())


async def prune_old_events_and_deliveries(
    session: AsyncSession,
    older_than_days: int,
) -> int:
    """Delete events (and cascaded deliveries) older than N days. Returns count deleted."""
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    # Delete deliveries for old events first (FK)
    subq = select(Event.id).where(Event.created_at < cutoff)
    await session.execute(delete(Delivery).where(Delivery.event_id.in_(subq)))
    result = await session.execute(delete(Event).where(Event.created_at < cutoff))
    await session.commit()
    return result.rowcount or 0

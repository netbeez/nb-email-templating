"""SQLAlchemy async models for events and deliveries; WAL mode and indexes."""

from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import Index, String, Text, Integer, DateTime, Boolean, ForeignKey, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Event(Base):
    """Webhook event with status lifecycle: received -> processing -> delivered | failed."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # received, processing, delivered, failed
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    deliveries: Mapped[list["Delivery"]] = relationship("Delivery", back_populates="event", order_by="Delivery.created_at")


class Delivery(Base):
    """Record of an email delivery attempt (success or failure)."""

    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    event: Mapped["Event"] = relationship("Event", back_populates="deliveries")


# Indexes for common queries
Index("ix_events_status_created", Event.status, Event.created_at)
Index("ix_deliveries_created", Delivery.created_at)


def get_engine(database_url: str):
    """Create async engine with SQLite. Caller should set WAL on connect."""
    return create_async_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


async def init_db(engine) -> None:
    """Create tables and enable WAL."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA journal_mode=WAL"))


def get_session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session

from datetime import UTC, datetime, timedelta
from functools import lru_cache

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import get_settings


class UTCDateTime(TypeDecorator):
    """SQLite drops timezone info; normalize both dialects at the persistence boundary."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("An explicit timezone is required")
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    engine = create_engine(
        url,
        pool_pre_ping=True,
        **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}),
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


@lru_cache
def clock_offset() -> timedelta:
    """Shift applied to the real clock when DEMO_NOW is set, fixed when first needed."""
    value = get_settings().demo_now
    if not value:
        return timedelta(0)
    target = datetime.fromisoformat(value)
    if target.tzinfo is None:
        raise ValueError("DEMO_NOW needs a UTC offset, for example 2026-10-13T08:00:00-07:00")
    return target - datetime.now(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC) + clock_offset()

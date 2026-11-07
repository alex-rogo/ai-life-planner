"""Demo-only tools: empty the planner, or reload the sample week with the demo Canvas feed."""

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import clock_offset, utcnow
from app.models import (
    ActivityEvent,
    CalendarSource,
    ChatMessage,
    CheckedItem,
    ExternalEvent,
    Goal,
    Obligation,
    Proposal,
    ScheduleSession,
    Suggestion,
    Task,
)
from app.seed import add_sample_data
from app.services import feeds
from app.services.resources import preferences
from app.services.upkeep import replan

# Children before parents. Preferences are settings, not data, so they stay.
TABLES = [
    CheckedItem,
    ChatMessage,
    Proposal,
    Suggestion,
    ScheduleSession,
    ExternalEvent,
    CalendarSource,
    Task,
    Goal,
    Obligation,
    ActivityEvent,
]


def allowed(settings: Settings) -> bool:
    return settings.ai_mode == "demo" or bool(clock_offset())


def _guard(settings: Settings) -> None:
    if not allowed(settings):
        raise HTTPException(403, "Sample data tools are only available in demo mode.")


def clear(db: Session, settings: Settings) -> None:
    """Remove every goal, task, event, session, connected calendar and chat message."""
    _guard(settings)
    prefs = preferences(db, lock=True)
    for model in TABLES:
        db.execute(delete(model))
    prefs.planned_through = None
    db.flush()
    db.expire_all()


def populate(db: Session, settings: Settings) -> None:
    """Start over with the sample week and the demo Canvas feed, planned once."""
    clear(db, settings)
    add_sample_data(db)
    now = utcnow()
    # The demo feed is generated locally, so no network access happens under the lock.
    source = CalendarSource(name=feeds.NAMES["demo"], provider="demo", url=feeds.DEMO_URL)
    db.add(source)
    db.flush()
    feeds.store(db, source, feeds.pull(feeds.DEMO_URL, now, feeds.timezone(db)), now)
    replan(db, now)

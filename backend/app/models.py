import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    deadline = mapped_column(UTCDateTime, nullable=True)
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0 AND duration_minutes % 15 = 0"),
        CheckConstraint("completed_minutes >= 0"),
        CheckConstraint("priority BETWEEN 1 AND 5"),
        CheckConstraint("min_session_minutes >= 15 AND max_session_minutes >= min_session_minutes"),
        CheckConstraint("status IN ('pending', 'completed', 'cancelled')"),
        CheckConstraint("recurrence IN ('none', 'daily', 'weekly')"),
        CheckConstraint("sessions_per_week BETWEEN 1 AND 7"),
        CheckConstraint("category IN ('focus', 'routine', 'personal', 'errand')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    completed_minutes: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    deadline = mapped_column(UTCDateTime, nullable=True, index=True)
    not_before = mapped_column(UTCDateTime, nullable=True)
    min_session_minutes: Mapped[int] = mapped_column(Integer, default=30)
    max_session_minutes: Mapped[int] = mapped_column(Integer, default=90)
    recurrence: Mapped[str] = mapped_column(String(10), default="none")
    sessions_per_week: Mapped[int] = mapped_column(Integer, default=3)
    activity_apps: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(12), default="focus", server_default="focus")
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Obligation(Base):
    __tablename__ = "obligations"
    __table_args__ = (
        CheckConstraint("kind IN ('commitment', 'appointment', 'interview', 'personal')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    weekdays: Mapped[list] = mapped_column(JSON)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    kind: Mapped[str] = mapped_column(String(12), default="commitment", server_default="commitment")


class Preference(Base):
    __tablename__ = "preferences"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Los_Angeles")
    sleep_start: Mapped[str] = mapped_column(String(5), default="23:00")
    sleep_end: Mapped[str] = mapped_column(String(5), default="07:00")
    available_start: Mapped[str] = mapped_column(String(5), default="07:00")
    available_end: Mapped[str] = mapped_column(String(5), default="23:00")
    preferred_start: Mapped[str] = mapped_column(String(5), default="09:00")
    preferred_end: Mapped[str] = mapped_column(String(5), default="17:00")
    break_minutes: Mapped[int] = mapped_column(Integer, default=15)
    stability_weight: Mapped[int] = mapped_column(Integer, default=8)
    preferred_weight: Mapped[int] = mapped_column(Integer, default=3)
    break_weight: Mapped[int] = mapped_column(Integer, default=10)
    context_weight: Mapped[int] = mapped_column(Integer, default=5)
    spread_weight: Mapped[int] = mapped_column(Integer, default=20)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Last local date covered by a successful plan; the API extends the horizon automatically.
    planned_through: Mapped[str | None] = mapped_column(String(10), nullable=True)


class ScheduleSession(Base):
    __tablename__ = "schedule_sessions"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at"),
        CheckConstraint("status IN ('planned', 'completed', 'skipped', 'missed')"),
        CheckConstraint("credited_minutes >= 0"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    obligation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("obligations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    starts_at = mapped_column(UTCDateTime, nullable=False, index=True)
    ends_at = mapped_column(UTCDateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), default="planned")
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    credited_minutes: Mapped[int] = mapped_column(Integer, default=0)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at"),
        CheckConstraint("state IN ('active', 'idle', 'unknown')"),
        CheckConstraint("idle_seconds >= 0"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    starts_at = mapped_column(UTCDateTime, nullable=False, index=True)
    ends_at = mapped_column(UTCDateTime, nullable=False, index=True)
    app_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(12))
    idle_seconds: Mapped[int] = mapped_column(Integer)
    received_at = mapped_column(UTCDateTime, nullable=False, default=utcnow, index=True)


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (CheckConstraint("status IN ('pending', 'confirmed', 'dismissed')"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedule_sessions.id", ondelete="CASCADE"), unique=True
    )
    message: Mapped[str] = mapped_column(Text)
    remaining_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(12))
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow, index=True)


class Proposal(Base):
    """An assistant change set previewed against a rolled-back transaction until applied."""

    __tablename__ = "proposals"
    __table_args__ = (CheckConstraint("status IN ('pending', 'applied', 'discarded', 'undone')"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    batch: Mapped[dict] = mapped_column(JSON)
    plan: Mapped[dict] = mapped_column(JSON)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    footer: Mapped[str] = mapped_column(Text, default="")
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    # State captured immediately before applying, and a hash of the state right after.
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The previewed end state and a hash of the state it was computed from. If nothing has
    # changed since the preview, applying writes exactly this instead of solving again.
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    base_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow, index=True)


class CalendarSource(Base):
    """A subscribed calendar feed (.ics). The URL is a secret and never leaves the backend."""

    __tablename__ = "calendar_sources"
    __table_args__ = (
        CheckConstraint("provider IN ('canvas', 'google', 'outlook', 'apple', 'other', 'demo')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(12))
    url: Mapped[str] = mapped_column(Text)
    last_synced_at = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ExternalEvent(Base):
    """An imported, read-only calendar item. Timed events block planning; Tomo never moves them."""

    __tablename__ = "external_events"
    __table_args__ = (
        CheckConstraint("kind IN ('event', 'deadline', 'all_day')"),
        CheckConstraint("ends_at >= starts_at"),
        UniqueConstraint("source_id", "uid"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_sources.id", ondelete="CASCADE"), index=True
    )
    # The feed's UID, plus the occurrence start for instances of repeating events.
    uid: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    course: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str] = mapped_column(String(300), default="")
    starts_at = mapped_column(UTCDateTime, nullable=False, index=True)
    ends_at = mapped_column(UTCDateTime, nullable=False, index=True)

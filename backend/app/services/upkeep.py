"""Work the API does on its own so the interface never has to ask for it."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    CalendarSource,
    ExternalEvent,
    Goal,
    Obligation,
    ScheduleSession,
    Suggestion,
    Task,
)
from app.schemas import PlanRequest, SessionOut, SessionPatch
from app.services.resources import preferences, update_session
from app.services.scheduler import generate_plan

HORIZON_DAYS = 7
# While the companion is enabled, leave time for idle evidence to become a suggestion first.
MONITORING_GRACE = timedelta(minutes=30)


def settle(db: Session, now: datetime | None = None) -> int:
    """Credit elapsed planned work as done. Corrections happen through the assistant."""
    now = now or utcnow()
    grace = MONITORING_GRACE if preferences(db).monitoring_enabled else timedelta(0)
    due = db.scalars(
        select(ScheduleSession).where(
            ScheduleSession.task_id.is_not(None),
            ScheduleSession.status == "planned",
            ScheduleSession.ends_at <= now - grace,
        )
    ).all()
    waiting = set(db.scalars(select(Suggestion.session_id).where(Suggestion.status == "pending")))
    targets = [s.id for s in due if s.id not in waiting]
    if not targets:
        return 0
    preferences(db, lock=True)
    for identifier in targets:
        update_session(db, identifier, SessionPatch(status="completed"))
    return len(targets)


def replan(db: Session, now: datetime | None = None):
    """Replan the standard horizon after any change to what needs scheduling."""
    return generate_plan(db, PlanRequest(days=HORIZON_DAYS), now)


def ensure_plan(db: Session, now: datetime | None = None) -> None:
    """Keep a full week planned as days pass; failures keep the existing schedule."""
    now = now or utcnow()
    prefs = preferences(db)
    today = now.astimezone(ZoneInfo(prefs.timezone)).date()
    target = (today + timedelta(days=HORIZON_DAYS - 1)).isoformat()
    if prefs.planned_through and prefs.planned_through >= target:
        return
    try:
        # generate_plan validates and solves before its first write, so failure leaves no changes.
        replan(db, now)
    except HTTPException:
        # A conflict is reported when the user next changes something; reads still succeed.
        pass


def session_views(db: Session, rows) -> list[dict]:
    """JSON-ready sessions with category, goal subtitle and deadline for the calendar."""
    task_ids = {r.task_id for r in rows if r.task_id}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(task_ids)))}
    goal_ids = {t.goal_id for t in tasks.values() if t.goal_id}
    goals = {g.id: g for g in db.scalars(select(Goal).where(Goal.id.in_(goal_ids)))}
    views = []
    for row in rows:
        view = SessionOut.model_validate(row).model_dump(mode="json")
        task = tasks.get(row.task_id)
        if task:
            goal = goals.get(task.goal_id)
            view.update(
                category=task.category,
                subtitle=goal.title if goal else None,
                deadline=task.deadline.isoformat() if task.deadline else None,
            )
        else:
            view.update(category="fixed", subtitle="Fixed", deadline=None)
        views.append(view)
    return views


def sessions_between(db: Session, start: datetime, end: datetime) -> list[ScheduleSession]:
    return db.scalars(
        select(ScheduleSession)
        .where(ScheduleSession.ends_at > start, ScheduleSession.starts_at < end)
        .order_by(ScheduleSession.starts_at)
        .limit(2000)
    ).all()


def occurrences(obligation: Obligation, first: date, last: date):
    """Local dates in [first, last] on which an obligation happens."""
    day = max(first, date.fromisoformat(obligation.start_date)) if obligation.start_date else first
    stop = min(last, date.fromisoformat(obligation.end_date)) if obligation.end_date else last
    while day <= stop:
        if day.weekday() in obligation.weekdays:
            yield day
        day += timedelta(days=1)


def external_views(
    db: Session, start: datetime | None = None, end: datetime | None = None
) -> list[dict]:
    """Timed events from connected calendars, shaped like sessions: fixed, locked, read-only."""
    statement = (
        select(ExternalEvent, CalendarSource.name)
        .join(CalendarSource)
        .where(ExternalEvent.kind == "event")
        .order_by(ExternalEvent.starts_at)
    )
    if start:
        statement = statement.where(ExternalEvent.ends_at > start)
    if end:
        statement = statement.where(ExternalEvent.starts_at < end)
    return [
        {
            "id": str(event.id),
            "task_id": None,
            "obligation_id": None,
            "title": event.title,
            "starts_at": event.starts_at.isoformat(),
            "ends_at": event.ends_at.isoformat(),
            "status": "planned",
            "locked": True,
            "credited_minutes": 0,
            "category": "fixed",
            "subtitle": event.course or source,
            "deadline": None,
            "change": None,
            "external": True,
        }
        for event, source in db.execute(statement.limit(2000))
    ]

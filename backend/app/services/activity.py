import math
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ActivityEvent, ScheduleSession, Suggestion, Task
from app.schemas import ActivityBatch, PlanRequest, SessionPatch, SuggestionDecision
from app.services.resources import preferences, require, update_session
from app.services.scheduler import generate_plan


def ingest(db: Session, batch: ActivityBatch):
    prefs = preferences(db, lock=True)
    if not prefs.monitoring_enabled:
        raise HTTPException(
            403, "Monitoring is disabled. Enable it in Settings before sending activity."
        )
    now = utcnow()
    accepted = 0
    for item in sorted(batch.events, key=lambda e: e.starts_at):
        if db.get(ActivityEvent, item.id):
            continue
        if item.ends_at > now + timedelta(seconds=5) or item.starts_at < now - timedelta(days=1):
            raise HTTPException(
                422, "Activity must be from the last 24 hours and not in the future."
            )
        overlaps = db.scalar(
            select(ActivityEvent.id)
            .where(ActivityEvent.starts_at < item.ends_at, ActivityEvent.ends_at > item.starts_at)
            .limit(1)
        )
        if overlaps:
            raise HTTPException(
                409, "Activity intervals must not overlap; use one companion agent."
            )
        db.add(ActivityEvent(**item.model_dump()))
        db.flush()
        accepted += 1
    # Keep monitoring data bounded; suggestions and schedule history have independent lifetimes.
    db.execute(delete(ActivityEvent).where(ActivityEvent.ends_at < now - timedelta(days=7)))
    evaluate(db, now)
    return {"accepted": accepted, "monitoring_enabled": True}


def evaluate(db: Session, now):
    sessions = db.scalars(
        select(ScheduleSession).where(
            ScheduleSession.task_id.is_not(None),
            ScheduleSession.status == "planned",
            ScheduleSession.starts_at <= now - timedelta(minutes=15),
            ScheduleSession.ends_at > now - timedelta(hours=24),
        )
    ).all()
    for session in sessions:
        if db.scalar(select(Suggestion.id).where(Suggestion.session_id == session.id)):
            continue
        task = require(db, Task, session.task_id)
        if task.status != "pending":
            continue
        until = min(now, session.ends_at)
        events = db.scalars(
            select(ActivityEvent).where(
                ActivityEvent.starts_at < until, ActivityEvent.ends_at > session.starts_at
            )
        ).all()
        idle, unrelated, compatible, unknown = 0, 0, 0, 0
        for event in events:
            seconds = max(
                0,
                (
                    min(event.ends_at, until) - max(event.starts_at, session.starts_at)
                ).total_seconds(),
            )
            if event.state == "idle":
                idle += seconds
            elif event.state == "active" and task.activity_apps and event.app_name:
                if event.app_name.lower() in task.activity_apps:
                    compatible += seconds
                else:
                    unrelated += seconds
            else:
                unknown += seconds
        evidence = idle + unrelated
        if evidence < 15 * 60:
            continue
        duration = int((session.ends_at - session.starts_at).total_seconds() // 60)
        # Compatible application activity is never credited as completed work.
        db.add(
            Suggestion(
                session_id=session.id,
                remaining_minutes=duration,
                message=f"{task.title}: at least {math.floor(evidence / 60)} minutes "
                "were idle or in unassociated apps. This is uncertain evidence, and your "
                f"session is still planned. Reschedule the {duration} unconfirmed minutes?",
            )
        )
    db.flush()


def decide(db: Session, identifier, data: SuggestionDecision):
    preferences(db, lock=True)
    row = require(db, Suggestion, identifier)
    if row.status != "pending":
        return {"status": row.status, "plan": None}
    if data.decision == "dismiss":
        row.status = "dismissed"
        db.flush()
        return {"status": row.status, "plan": None}
    session = require(db, ScheduleSession, row.session_id)
    if session.status != "planned":
        raise HTTPException(409, "This session has already been resolved; dismiss the suggestion.")
    if session.locked:
        raise HTTPException(409, "Unlock this session before confirming a reschedule.")
    row.status = "confirmed"
    update_session(db, session.id, SessionPatch(status="missed"))
    result = generate_plan(db, PlanRequest(days=7))
    return {"status": row.status, "plan": result.model_dump(mode="json")}


def connection_status(db: Session):
    prefs = preferences(db)
    last = db.scalar(select(ActivityEvent).order_by(ActivityEvent.received_at.desc()).limit(1))
    connected = bool(
        prefs.monitoring_enabled and last and (utcnow() - last.received_at).total_seconds() < 120
    )
    return {
        "agent_connected": connected,
        "last_activity_at": last.received_at if last else None,
        "activity_state": last.state if connected else "unknown",
    }

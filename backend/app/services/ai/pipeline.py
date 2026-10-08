from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import ChatMessage, Goal, ScheduleSession, Task
from app.schemas import ChatIn, GoalOut, Preferences, SessionPatch, TaskOut, TaskPatch
from app.services import resources
from app.services.ai.actions import (
    Clarify,
    CompleteTask,
    CreateGoal,
    CreateObligation,
    CreateTask,
    Reschedule,
    SetPreference,
    UpdateTask,
)
from app.services.ai.interpreter import interpret
from app.services.scheduler import generate_plan, local_midnight


def context_for(db: Session, now: datetime) -> dict:
    return {
        "now": now.isoformat(),
        "preferences": Preferences.model_validate(resources.preferences(db)).model_dump(
            mode="json"
        ),
        "tasks": [
            TaskOut.model_validate(t).model_dump(mode="json")
            for t in db.scalars(select(Task).order_by(Task.created_at).limit(200))
        ],
        "goals": [
            GoalOut.model_validate(g).model_dump(mode="json")
            for g in db.scalars(select(Goal).order_by(Goal.created_at).limit(100))
        ],
        "recent_messages": [
            {"role": m.role, "content": m.content}
            for m in reversed(
                db.scalars(
                    select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(6)
                ).all()
            )
        ],
    }


def postpone(db: Session, action: Reschedule, now: datetime):
    tasks = (
        [resources.require(db, Task, action.task_id)]
        if action.task_id
        else db.scalars(select(Task).where(Task.status == "pending")).all()
    )
    for task in tasks:
        if task.status != "pending":
            raise HTTPException(409, "Only pending tasks can be rescheduled")
        changes = {}
        if action.delay_minutes or action.tonight:
            not_before = now + timedelta(minutes=action.delay_minutes)
            if action.tonight:
                tz = ZoneInfo(resources.preferences(db).timezone)
                evening = datetime.combine(
                    now.astimezone(tz).date(), time(18), tzinfo=tz
                ).astimezone(UTC)
                not_before = max(not_before, evening)
            changes["not_before"] = not_before
            active = db.scalars(
                select(ScheduleSession).where(
                    ScheduleSession.task_id == task.id,
                    ScheduleSession.status == "planned",
                    ScheduleSession.starts_at <= now,
                    ScheduleSession.ends_at > now,
                )
            ).all()
            for session in active:
                if session.locked:
                    raise HTTPException(409, "Unlock the active session before postponing it")
                resources.update_session(db, session.id, SessionPatch(status="skipped"))
        if action.priority is not None:
            changes["priority"] = action.priority
        if changes:
            resources.update_task(db, task.id, TaskPatch(**changes))


def complete(db: Session, action: CompleteTask, now: datetime):
    task = resources.require(db, Task, action.task_id)
    session = db.scalar(
        select(ScheduleSession)
        .where(
            ScheduleSession.task_id == task.id,
            ScheduleSession.status == "planned",
            ScheduleSession.starts_at <= now,
            ScheduleSession.ends_at > now,
        )
        .order_by(ScheduleSession.starts_at)
    )
    if not session and task.recurrence != "none":
        tz = ZoneInfo(resources.preferences(db).timezone)
        today = now.astimezone(tz).date()
        session = db.scalar(
            select(ScheduleSession)
            .where(
                ScheduleSession.task_id == task.id,
                ScheduleSession.status == "planned",
                ScheduleSession.starts_at >= local_midnight(today, tz),
                ScheduleSession.starts_at < local_midnight(today + timedelta(days=1), tz),
            )
            .order_by(ScheduleSession.starts_at.desc())
        )
    if session:
        resources.update_session(
            db, session.id, SessionPatch(status="completed", actual_minutes=action.actual_minutes)
        )
    elif task.recurrence == "none":
        resources.update_task(db, task.id, TaskPatch(status="completed"))
    else:
        raise HTTPException(409, "Generate a session for today before completing recurring work")


def execute_chat(db: Session, data: ChatIn, settings: Settings):
    now = utcnow()
    # Interpret before acquiring the write lock; network latency must not hold DB locks.
    batch = interpret(settings, data.message, context_for(db, now))
    resources.preferences(db, lock=True)
    created = []
    clarifications = [a.question for a in batch.actions if isinstance(a, Clarify)]
    plan = None
    if clarifications:
        explanation = " ".join(clarifications)
    else:
        for action in batch.actions:
            if isinstance(action, CreateGoal):
                goal = resources.create_goal(db, action.goal)
                created.append(str(goal.id))
                for task in action.tasks:
                    if task.goal_id:
                        raise HTTPException(422, "New goal tasks cannot refer to a different goal")
                    resources.create_task(db, task.model_copy(update={"goal_id": goal.id}))
            elif isinstance(action, CreateTask):
                created.append(str(resources.create_task(db, action.task).id))
            elif isinstance(action, UpdateTask):
                resources.update_task(db, action.task_id, action.changes)
            elif isinstance(action, CreateObligation):
                resources.save_obligation(db, action.obligation)
            elif isinstance(action, SetPreference):
                if (
                    action.preferences.monitoring_enabled
                    != resources.preferences(db).monitoring_enabled
                ):
                    raise HTTPException(
                        422,
                        "Change activity monitoring explicitly in Settings; assistant preferences only change scheduling.",
                    )
                resources.save_preferences(db, action.preferences)
            elif isinstance(action, Reschedule):
                postpone(db, action, now)
            elif isinstance(action, CompleteTask):
                complete(db, action, now)
        plan = generate_plan(db, data.plan, now)
        explanation = batch.explanation + " " + plan.explanation
    if batch.defaults:
        explanation += "\nDefaults: " + "; ".join(batch.defaults)
    db.add_all(
        [
            ChatMessage(role="user", content=data.message, mode=settings.ai_mode),
            ChatMessage(role="assistant", content=explanation, mode=settings.ai_mode),
        ]
    )
    db.flush()
    return {
        "reply": explanation,
        "mode": settings.ai_mode,
        "defaults": batch.defaults,
        "created_ids": created,
        "needs_clarification": bool(clarifications),
        "plan": plan.model_dump(mode="json") if plan else None,
    }

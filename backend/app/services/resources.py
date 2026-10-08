from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Goal, Obligation, Preference, ScheduleSession, Task
from app.schemas import (
    GoalCreate,
    ObligationCreate,
    Preferences,
    SessionPatch,
    TaskCreate,
    TaskPatch,
)


def require(db: Session, model, identifier):
    item = db.get(model, identifier)
    if item is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return item


def preferences(db: Session, lock=False) -> Preference:
    statement = select(Preference).where(Preference.id == 1)
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise HTTPException(503, "Database is not initialized. Run alembic upgrade head.")
    return row


def create_goal(db: Session, data: GoalCreate) -> Goal:
    row = Goal(**data.model_dump())
    db.add(row)
    db.flush()
    return row


def create_task(db: Session, data: TaskCreate) -> Task:
    if data.goal_id:
        require(db, Goal, data.goal_id)
    row = Task(**data.model_dump())
    db.add(row)
    db.flush()
    return row


def invalidate_future(db: Session, task_id: UUID):
    db.execute(
        delete(ScheduleSession).where(
            ScheduleSession.task_id == task_id,
            ScheduleSession.status == "planned",
            ScheduleSession.locked.is_(False),
            ScheduleSession.starts_at > utcnow(),
        )
    )


def update_task(db: Session, task_id: UUID, patch: TaskPatch) -> Task:
    row = require(db, Task, task_id)
    current = TaskCreate.model_validate(row).model_dump()
    current.update(patch.model_dump(exclude_unset=True))
    data = TaskCreate.model_validate(current)
    if data.goal_id:
        require(db, Goal, data.goal_id)
    protected = db.scalars(
        select(ScheduleSession).where(
            ScheduleSession.task_id == row.id,
            ScheduleSession.status == "planned",
            ScheduleSession.ends_at > utcnow(),
            (ScheduleSession.locked.is_(True) | (ScheduleSession.starts_at <= utcnow())),
        )
    ).all()
    for session in protected:
        duration = int((session.ends_at - session.starts_at).total_seconds() // 60)
        if (
            (data.deadline and session.ends_at > data.deadline)
            or (data.not_before and session.starts_at < data.not_before)
            or duration < data.min_session_minutes
            or duration > data.max_session_minutes
        ):
            raise HTTPException(
                409, "This edit conflicts with a protected session. Unlock or resolve it first."
            )
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    if patch.model_fields_set:
        invalidate_future(db, row.id)
    db.flush()
    return row


def save_preferences(db: Session, data: Preferences) -> Preference:
    row = preferences(db, lock=True)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.flush()
    return row


def save_obligation(db: Session, data: ObligationCreate, identifier=None) -> Obligation:
    row = require(db, Obligation, identifier) if identifier else Obligation()
    for key, value in data.model_dump(mode="json").items():
        setattr(row, key, value)
    if identifier:
        db.execute(
            delete(ScheduleSession).where(
                ScheduleSession.obligation_id == identifier,
                ScheduleSession.status == "planned",
                ScheduleSession.starts_at > utcnow(),
            )
        )
    db.add(row)
    db.flush()
    return row


def update_session(db: Session, identifier: UUID, data: SessionPatch) -> ScheduleSession:
    row = require(db, ScheduleSession, identifier)
    if row.obligation_id and data.status:
        raise HTTPException(422, "Fixed obligations cannot be marked as flexible work")
    if row.status != "planned" and data.status and row.status != data.status:
        raise HTTPException(409, "A resolved session cannot change status; edit the task instead")
    if data.actual_minutes is not None and data.status != "completed":
        raise HTTPException(422, "Actual minutes apply only when completing a session")
    if data.locked is not None:
        if row.obligation_id and not data.locked:
            raise HTTPException(422, "Fixed obligations cannot be unlocked")
        row.locked = data.locked
    if data.status and row.status == "planned":
        row.status = data.status
        if data.status == "completed" and row.task_id:
            duration = int((row.ends_at - row.starts_at).total_seconds() // 60)
            if data.actual_minutes is not None and data.actual_minutes > duration:
                raise HTTPException(422, "Actual minutes cannot exceed the reserved session")
            row.credited_minutes = (
                data.actual_minutes if data.actual_minutes is not None else duration
            )
            task = require(db, Task, row.task_id)
            task.completed_minutes += row.credited_minutes
            if task.recurrence == "none" and task.completed_minutes >= task.duration_minutes:
                task.status = "completed"
                invalidate_future(db, task.id)
    db.flush()
    return row

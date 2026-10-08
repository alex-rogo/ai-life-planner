from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Obligation, Preference, ScheduleSession
from app.schemas import PlanRequest, SessionPatch, TaskCreate
from app.services.resources import create_task, update_session
from app.services.scheduler import generate_plan

NOW = datetime(2027, 1, 4, 15, 0, tzinfo=UTC)  # Monday 07:00 Los Angeles
DAY = NOW.date()


def add(db, **kwargs):
    task = create_task(db, TaskCreate(title=kwargs.pop("title", "Work"), **kwargs))
    task.created_at = NOW - timedelta(days=1)
    db.flush()
    return task


def plan(db, days=1, now=NOW):
    return generate_plan(db, PlanRequest(start_date=DAY, days=days), now)


def test_non_overlap_deadline_sleep_and_fixed(db):
    task = add(db, duration_minutes=180, deadline=NOW + timedelta(hours=7))
    obligation = Obligation(title="Class", weekdays=[0], start_time="09:00", end_time="11:00")
    db.add(obligation)
    db.flush()
    result = plan(db)
    assert not result.unscheduled
    blocks = sorted(result.sessions, key=lambda s: s.starts_at)
    assert all(a.ends_at <= b.starts_at for a, b in zip(blocks, blocks[1:]))
    fixed = next(s for s in blocks if s.obligation_id)
    assert fixed.starts_at == NOW + timedelta(hours=2)
    assert fixed.locked
    assert all(s.ends_at <= task.deadline for s in blocks if s.task_id)
    assert all(
        30 <= (s.ends_at - s.starts_at).total_seconds() / 60 <= 90 for s in blocks if s.task_id
    )


def test_priority_wins_when_capacity_insufficient(db):
    prefs = db.get(Preference, 1)
    prefs.available_start, prefs.available_end = "09:00", "10:00"
    low = add(db, title="Low", priority=1)
    high = add(db, title="High", priority=5)
    result = plan(db)
    assert [s.task_id for s in result.sessions] == [high.id]
    assert [u.task_id for u in result.unscheduled] == [low.id]


def test_expired_deadline_is_reported(db):
    add(db, deadline=NOW - timedelta(minutes=1))
    result = plan(db)
    assert not result.sessions
    assert result.unscheduled and "deadline" in result.unscheduled[0].reason


def test_conflicting_obligations_preserve_existing_schedule(db):
    add(db)
    initial = plan(db)
    db.add_all(
        [
            Obligation(title="One", weekdays=[0], start_time="10:00", end_time="12:00"),
            Obligation(title="Two", weekdays=[0], start_time="11:00", end_time="13:00"),
        ]
    )
    db.flush()
    with pytest.raises(HTTPException) as error:
        plan(db)
    assert error.value.status_code == 409
    assert len(db.scalars(select(ScheduleSession)).all()) == len(initial.sessions)


def test_missed_session_reschedules_and_completed_locked_stay(db):
    add(db, duration_minutes=180, max_session_minutes=60)
    initial = plan(db)
    rows = db.scalars(select(ScheduleSession).order_by(ScheduleSession.starts_at)).all()
    update_session(db, rows[0].id, SessionPatch(status="missed"))
    update_session(db, rows[1].id, SessionPatch(status="completed"))
    update_session(db, rows[2].id, SessionPatch(locked=True))
    result = plan(db, now=rows[1].ends_at)
    assert any(s.status == "missed" and s.id == rows[0].id for s in result.sessions)
    assert any(s.status == "completed" and s.id == rows[1].id for s in result.sessions)
    assert any(s.locked and s.id == rows[2].id for s in result.sessions)
    assert sum(s.status == "planned" for s in result.sessions) == 2
    assert len(initial.sessions) == 3


def test_daily_weekly_and_stable_replan(db):
    daily = add(db, title="Daily", recurrence="daily")
    weekly = add(db, title="Workout", recurrence="weekly", sessions_per_week=3)
    initial = plan(db, days=7)
    assert sum(s.task_id == daily.id for s in initial.sessions) == 7
    workouts = [s for s in initial.sessions if s.task_id == weekly.id]
    assert len(workouts) == 3
    assert len({s.starts_at.date() for s in workouts}) == 3
    again = plan(db, days=7)
    assert {s.id for s in initial.sessions} == {s.id for s in again.sessions}


def test_dst_horizon(db):
    task = add(db, recurrence="daily")
    task.created_at = datetime(2027, 3, 13, tzinfo=UTC)
    result = generate_plan(
        db,
        PlanRequest(start_date=datetime(2027, 3, 13).date(), days=3),
        datetime(2027, 3, 13, 15, tzinfo=UTC),
    )
    assert len(result.sessions) == 3
    assert all(s.ends_at - s.starts_at == timedelta(hours=1) for s in result.sessions)


def test_completion_is_idempotent_and_actual_minutes(db):
    task = add(db)
    result = plan(db)
    identifier = result.sessions[0].id
    update_session(db, identifier, SessionPatch(status="completed", actual_minutes=30))
    update_session(db, identifier, SessionPatch(status="completed", actual_minutes=30))
    assert task.completed_minutes == 30
    assert task.status == "pending"
    result = plan(db)
    assert any(s.status == "planned" for s in result.sessions)


def test_locked_outside_horizon_reserves_remaining_work(db):
    task = add(db)
    db.add(
        ScheduleSession(
            task_id=task.id,
            title=task.title,
            starts_at=NOW + timedelta(days=8),
            ends_at=NOW + timedelta(days=8, hours=1),
            locked=True,
        )
    )
    db.flush()
    assert not plan(db).sessions

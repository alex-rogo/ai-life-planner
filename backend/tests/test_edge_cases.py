from datetime import timedelta

import pytest
from fastapi import HTTPException
from test_scheduler import DAY, NOW, add, plan

from app.models import Obligation, Preference, ScheduleSession
from app.schemas import PlanRequest, SessionPatch
from app.services.resources import update_session
from app.services.scheduler import generate_plan


def test_partial_daily_completion_replans_remaining_minutes(db):
    task = add(db, recurrence="daily")
    first = plan(db)
    update_session(db, first.sessions[0].id, SessionPatch(status="completed", actual_minutes=30))
    result = plan(db)
    assert (
        sum(
            (s.ends_at - s.starts_at).total_seconds() / 60
            for s in result.sessions
            if s.status == "planned"
        )
        == 30
    )
    assert task.completed_minutes == 30


def test_non_quarter_availability_is_never_exceeded(db):
    prefs = db.get(Preference, 1)
    prefs.available_start, prefs.available_end = "09:05", "10:10"
    add(db, duration_minutes=60, min_session_minutes=60)
    result = plan(db)
    assert result.unscheduled
    assert not result.sessions


def test_adjacent_non_quarter_obligations_can_share_boundary(db):
    db.add_all(
        [
            Obligation(title="First", weekdays=[0], start_time="09:00", end_time="10:10"),
            Obligation(title="Second", weekdays=[0], start_time="10:10", end_time="11:00"),
        ]
    )
    db.flush()
    assert len(plan(db).sessions) == 2


def test_missing_minimum_remainder_is_reported(db):
    task = add(db, duration_minutes=60, min_session_minutes=60)
    task.completed_minutes = 15
    result = plan(db)
    assert result.unscheduled[0].minutes == 45


def test_fourteen_day_weekly_horizon(db):
    task = add(db, recurrence="weekly", sessions_per_week=2)
    result = plan(db, days=14)
    assert len([s for s in result.sessions if s.task_id == task.id]) == 4


def test_running_session_is_preserved(db):
    task = add(db)
    session = ScheduleSession(
        task_id=task.id,
        title=task.title,
        starts_at=NOW - timedelta(minutes=15),
        ends_at=NOW + timedelta(minutes=45),
    )
    db.add(session)
    db.flush()
    result = plan(db)
    assert result.sessions[0].id == session.id
    assert len(result.sessions) == 1


def test_past_planning_rejected(db):
    with pytest.raises(HTTPException) as exc:
        generate_plan(db, PlanRequest(start_date=DAY, days=1), NOW + timedelta(days=2))
    assert exc.value.status_code == 422


def test_preferred_hours_do_not_become_hard_bounds_late_at_night(db):
    late_now = NOW + timedelta(hours=15)
    add(db, duration_minutes=30)
    result = plan(db, now=late_now)
    assert len(result.sessions) == 1
    assert not result.unscheduled


def test_edit_cannot_violate_a_locked_deadline(db):
    from app.schemas import TaskPatch
    from app.services.resources import update_task

    task = add(db)
    result = plan(db)
    identifier = result.sessions[0].id
    update_session(db, identifier, SessionPatch(locked=True))
    with pytest.raises(HTTPException) as exc:
        update_task(db, task.id, TaskPatch(deadline=NOW + timedelta(minutes=1)))
    assert exc.value.status_code == 409


def test_new_sleep_window_conflicting_with_lock_is_reported(db):
    add(db)
    first = plan(db)
    update_session(db, first.sessions[0].id, SessionPatch(locked=True))
    prefs = db.get(Preference, 1)
    prefs.sleep_start, prefs.sleep_end = "08:00", "12:00"
    with pytest.raises(HTTPException) as exc:
        plan(db)
    assert exc.value.status_code == 409

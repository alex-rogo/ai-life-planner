from datetime import UTC, datetime, timedelta

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


def test_overlapping_obligations_are_allowed_and_block_work(db):
    add(db)
    db.add_all(
        [
            Obligation(title="Class", weekdays=[0], start_time="10:00", end_time="12:00"),
            Obligation(title="Bus", weekdays=[0], start_time="09:30", end_time="12:30"),
        ]
    )
    db.flush()
    result = plan(db)
    fixed = [s for s in result.sessions if s.obligation_id]
    assert {s.title for s in fixed} == {"Class", "Bus"}
    work = [s for s in result.sessions if s.task_id]
    assert work
    bus = next(s for s in fixed if s.title == "Bus")
    assert all(s.ends_at <= bus.starts_at or s.starts_at >= bus.ends_at for s in work)


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


def test_travel_goes_before_the_first_event_and_home_after_the_last(db):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Los_Angeles")
    db.add_all(
        [
            Obligation(
                title="Programming 342",
                weekdays=[0, 2],
                start_time="13:15",
                end_time="15:15",
                travel_minutes=30,
                travel_mode="bus",
            ),
            Obligation(
                title="Software engineering",
                weekdays=[1, 2],
                start_time="15:30",
                end_time="19:45",
                travel_minutes=30,
                travel_mode="bus",
            ),
        ]
    )
    db.flush()
    plan(db, days=3)
    plan(db, days=3)  # Replanning rebuilds trips instead of piling up copies.
    rows = db.scalars(select(ScheduleSession).order_by(ScheduleSession.starts_at)).all()

    def trips(weekday):
        return [
            (
                s.title,
                s.starts_at.astimezone(tz).strftime("%H:%M"),
                s.ends_at.astimezone(tz).strftime("%H:%M"),
            )
            for s in rows
            if s.travel and s.starts_at.astimezone(tz).weekday() == weekday
        ]

    assert trips(0) == [
        ("Bus to Programming 342", "12:45", "13:15"),
        ("Bus home", "15:15", "15:45"),
    ]
    assert trips(1) == [
        ("Bus to Software engineering", "15:00", "15:30"),
        ("Bus home", "19:45", "20:15"),
    ]
    # Wednesday: straight from one class to the next, so one ride there and one home.
    assert trips(2) == [
        ("Bus to Programming 342", "12:45", "13:15"),
        ("Bus home", "19:45", "20:15"),
    ]
    fixed = [s for s in rows if s.obligation_id]
    assert all(a.ends_at <= b.starts_at for a, b in zip(fixed, fixed[1:]))
    work = [s for s in rows if s.task_id]
    assert all(
        not (w.starts_at < f.ends_at and f.starts_at < w.ends_at) for w in work for f in fixed
    )


def test_time_windows_rest_days_and_spreading_across_the_week(db):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Los_Angeles")
    add(
        db,
        title="LeetCode",
        duration_minutes=60,
        recurrence="daily",
        window_start="10:00",
        window_end="22:00",
    )
    add(
        db,
        title="Workout",
        duration_minutes=60,
        recurrence="weekly",
        sessions_per_week=3,
        category="routine",
    )
    add(
        db,
        title="Project",
        duration_minutes=90,
        max_session_minutes=120,
        recurrence="weekly",
        sessions_per_week=3,
    )
    db.add(Obligation(title="Class", weekdays=[0, 1, 2, 3], start_time="13:00", end_time="18:00"))
    db.flush()
    plan(db, days=7)
    rows = [s for s in db.scalars(select(ScheduleSession)) if s.task_id]
    local = lambda s: s.starts_at.astimezone(tz)  # noqa: E731
    leetcode = [s for s in rows if s.title == "LeetCode"]
    assert len(leetcode) == 7
    assert all(local(s).hour >= 10 and s.ends_at.astimezone(tz).hour <= 22 for s in leetcode)
    workout_days = sorted(local(s).weekday() for s in rows if s.title == "Workout")
    assert len(workout_days) == 3
    assert all(b - a >= 2 for a, b in zip(workout_days, workout_days[1:]))
    # Long class days (Mon-Thu) get less flexible work than the free weekend.
    flexible = {d: 0 for d in range(7)}
    for s in rows:
        flexible[local(s).weekday()] += int((s.ends_at - s.starts_at).total_seconds() // 60)
    assert max(flexible[d] for d in range(4)) <= min(flexible[d] for d in (4, 5, 6))


def test_chosen_days_are_honoured_even_back_to_back(db):
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Los_Angeles")
    # Four workouts in a row, Fri-Mon, at 4 pm: no rest days forced between them.
    add(
        db,
        title="Workout",
        duration_minutes=60,
        recurrence="weekly",
        sessions_per_week=4,
        days=[4, 5, 6, 0],
        window_start="16:00",
        window_end="17:00",
    )
    plan(db, days=7)
    rows = [s for s in db.scalars(select(ScheduleSession)) if s.task_id]
    assert sorted(s.starts_at.astimezone(tz).weekday() for s in rows) == [0, 4, 5, 6]
    assert all(s.starts_at.astimezone(tz).hour == 16 for s in rows)

from datetime import timedelta
from zoneinfo import ZoneInfo

from app.db import utcnow
from app.models import Preference, ScheduleSession, Suggestion, Task
from app.services.upkeep import settle


def elapsed(db, title="Reading", minutes_ago=90):
    task = Task(title=title, duration_minutes=120, priority=3)
    db.add(task)
    db.flush()
    session = ScheduleSession(
        task_id=task.id,
        title=title,
        starts_at=utcnow() - timedelta(minutes=minutes_ago),
        ends_at=utcnow() - timedelta(minutes=minutes_ago - 60),
    )
    db.add(session)
    db.flush()
    return task, session


def test_elapsed_work_is_credited_without_a_check_off(db):
    task, session = elapsed(db)
    assert settle(db) == 1
    assert session.status == "completed"
    assert session.credited_minutes == 60
    assert task.completed_minutes == 60
    assert settle(db) == 0


def test_settle_waits_for_pending_activity_suggestions_and_monitoring_grace(db):
    _, waiting = elapsed(db, "Waiting")
    db.add(Suggestion(session_id=waiting.id, message="Idle", remaining_minutes=60))
    db.get(Preference, 1).monitoring_enabled = True
    _, recent = elapsed(db, "Recent", minutes_ago=70)
    db.flush()
    assert settle(db) == 0
    assert waiting.status == "planned"
    assert recent.status == "planned"


def test_crud_changes_replan_without_a_generate_step(client):
    task = client.post("/api/tasks", json={"title": "Write essay", "duration_minutes": 90})
    assert task.status_code == 201
    sessions = client.get("/api/sessions").json()
    mine = [s for s in sessions if s["task_id"] == task.json()["id"]]
    assert sum(1 for _ in mine) >= 1
    assert all(s["category"] == "focus" for s in mine)
    client.delete(f"/api/tasks/{task.json()['id']}")
    assert not [s for s in client.get("/api/sessions").json() if s["task_id"]]


def test_reads_extend_the_horizon_automatically(client, db):
    db.add(Task(title="Daily review", duration_minutes=30, recurrence="daily", priority=3))
    db.commit()
    assert db.get(Preference, 1).planned_through is None
    client.get("/api/overview")
    tz = ZoneInfo(db.get(Preference, 1).timezone)
    expected = (utcnow().astimezone(tz).date() + timedelta(days=6)).isoformat()
    assert db.get(Preference, 1).planned_through == expected


def test_overview_lists_events_deadlines_and_goal_progress(client, db):
    tz = ZoneInfo(db.get(Preference, 1).timezone)
    day = utcnow().astimezone(tz).date() + timedelta(days=3)
    client.post(
        "/api/obligations",
        json={
            "title": "Dentist",
            "kind": "appointment",
            "weekdays": [day.weekday()],
            "start_time": "08:30",
            "end_time": "09:30",
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
        },
    )
    deadline = (utcnow() + timedelta(days=5)).isoformat()
    goal = client.post("/api/goals", json={"title": "Launch site", "deadline": deadline}).json()
    client.post(
        "/api/tasks", json={"title": "Build pages", "goal_id": goal["id"], "deadline": deadline}
    )
    body = client.get("/api/overview").json()
    kinds = {item["title"]: item["kind"] for item in body["upcoming"]}
    assert kinds == {"Dentist": "Appointment", "Launch site": "Project"}
    assert body["goals"][0]["title"] == "Launch site"
    assert body["goals"][0]["progress"] == "0%"
    assert [s["label"] for s in body["stats"]] == ["Left today", "Free time", "Plan health"]
    week = client.get("/api/overview", params={"days": 7}).json()
    assert [s["label"] for s in week["stats"]] == ["Focus time", "Commitments", "Free evenings"]
    assert week["goals"][0]["progress"] == "0 / 1"
    assert len(week["prompts"]) == 3


def test_demo_clock_shifts_now_and_requires_an_offset(monkeypatch):
    from datetime import UTC, datetime

    import pytest

    from app import db as db_module
    from app.config import Settings

    try:
        monkeypatch.setattr(
            db_module, "get_settings", lambda: Settings(demo_now="2030-01-01T09:00:00+00:00")
        )
        db_module.clock_offset.cache_clear()
        assert abs(db_module.utcnow() - datetime(2030, 1, 1, 9, tzinfo=UTC)).total_seconds() < 5
        monkeypatch.setattr(
            db_module, "get_settings", lambda: Settings(demo_now="2030-01-01T09:00")
        )
        db_module.clock_offset.cache_clear()
        with pytest.raises(ValueError):
            db_module.utcnow()
    finally:
        db_module.clock_offset.cache_clear()


def test_demo_tools_clear_and_populate_and_are_demo_only(client, monkeypatch):
    client.post("/api/tasks", json={"title": "Mine"})
    client.post("/api/assistant", json={"message": "Schedule something"})
    assert client.post("/api/demo/clear").status_code == 204
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/sessions").json() == []
    assert client.get("/api/messages").json() == []

    assert client.post("/api/demo/populate").status_code == 204
    assert len(client.get("/api/goals").json()) == 4
    sessions = client.get("/api/sessions").json()
    assert any(s["task_id"] for s in sessions) and any(s["external"] for s in sessions)
    assert client.get("/api/calendars").json()[0]["provider"] == "demo"
    assert client.get("/api/system").json()["sample_data_tools"]

    monkeypatch.setattr("app.main.settings.ai_mode", "gemini")
    assert client.post("/api/demo/clear").status_code == 403
    assert len(client.get("/api/goals").json()) == 4

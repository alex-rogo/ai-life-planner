from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.db import utcnow
from app.models import Preference, ScheduleSession, Suggestion, Task

HEADERS = {"X-Agent-Token": "test-agent-token"}


def event(a, b, state="idle", app=None):
    return {
        "id": str(uuid4()),
        "starts_at": a.isoformat(),
        "ends_at": b.isoformat(),
        "state": state,
        "app_name": app,
        "idle_seconds": 300 if state == "idle" else 0,
    }


def enable(db):
    db.get(Preference, 1).monitoring_enabled = True
    db.commit()


def test_auth_opt_in_and_idempotent_ingestion(client, db):
    now = utcnow()
    body = {"events": [event(now - timedelta(seconds=30), now)]}
    assert client.post("/api/activity", json=body).status_code == 401
    assert client.post("/api/activity", json=body, headers=HEADERS).status_code == 403
    enable(db)
    assert client.post("/api/activity", json=body, headers=HEADERS).json()["accepted"] == 1
    assert client.post("/api/activity", json=body, headers=HEADERS).json()["accepted"] == 0
    assert client.get("/api/system").json()["agent_connected"]
    overlap = {"events": [event(now - timedelta(seconds=20), now)]}
    assert client.post("/api/activity", json=overlap, headers=HEADERS).status_code == 409


def test_uncertain_activity_only_suggests_then_confirm_reschedules(client, db):
    enable(db)
    now = utcnow()
    task = Task(title="LeetCode", duration_minutes=60, priority=3, activity_apps=["code.exe"])
    db.add(task)
    db.flush()
    session = ScheduleSession(
        task_id=task.id,
        title=task.title,
        starts_at=now - timedelta(minutes=30),
        ends_at=now + timedelta(minutes=30),
    )
    db.add(session)
    db.commit()
    reports = [
        event(now - timedelta(minutes=30 - i * 5), now - timedelta(minutes=25 - i * 5))
        for i in range(6)
    ]
    response = client.post("/api/activity", json={"events": reports}, headers=HEADERS)
    assert response.status_code == 200
    suggestion = client.get("/api/suggestions").json()[0]
    assert session.status == "planned"
    assert task.completed_minutes == 0
    assert suggestion["remaining_minutes"] == 60
    response = client.post(
        f"/api/suggestions/{suggestion['id']}/decision", json={"decision": "confirm"}
    )
    assert response.status_code == 200, response.text
    assert session.status == "missed"
    assert response.json()["plan"]["sessions"]
    # Confirming twice cannot create duplicate reservations.
    assert (
        client.post(
            f"/api/suggestions/{suggestion['id']}/decision", json={"decision": "confirm"}
        ).json()["plan"]
        is None
    )


def test_unknown_or_matching_apps_do_not_prove_work_or_create_suggestions(client, db):
    enable(db)
    now = utcnow()
    task = Task(title="Code", activity_apps=["code.exe"])
    db.add(task)
    db.flush()
    db.add(
        ScheduleSession(
            task_id=task.id,
            title=task.title,
            starts_at=now - timedelta(minutes=20),
            ends_at=now + timedelta(minutes=40),
        )
    )
    db.commit()
    reports = [
        event(
            now - timedelta(minutes=20 - i * 5),
            now - timedelta(minutes=15 - i * 5),
            "active",
            "Code.exe",
        )
        for i in range(4)
    ]
    assert (
        client.post("/api/activity", json={"events": reports}, headers=HEADERS).status_code == 200
    )
    assert db.scalar(select(Suggestion)) is None
    assert task.completed_minutes == 0


def test_dismiss_preserves_planned_session(client, db):
    enable(db)
    now = utcnow()
    task = Task(title="Work")
    db.add(task)
    db.flush()
    session = ScheduleSession(
        task_id=task.id,
        title=task.title,
        starts_at=now - timedelta(minutes=20),
        ends_at=now + timedelta(minutes=40),
    )
    db.add(session)
    db.flush()
    suggestion = Suggestion(
        session_id=session.id, message="Uncertain evidence", remaining_minutes=60
    )
    db.add(suggestion)
    db.commit()
    assert (
        client.post(
            f"/api/suggestions/{suggestion.id}/decision", json={"decision": "dismiss"}
        ).status_code
        == 200
    )
    assert session.status == "planned"


def test_future_events_and_paths_are_rejected(client, db):
    enable(db)
    now = utcnow()
    assert (
        client.post(
            "/api/activity",
            headers=HEADERS,
            json={"events": [event(now, now + timedelta(minutes=5))]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/activity",
            headers=HEADERS,
            json={"events": [event(now - timedelta(seconds=30), now, "active", "C:/code.exe")]},
        ).status_code
        == 422
    )

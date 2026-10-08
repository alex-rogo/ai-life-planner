from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task


def test_task_crud_and_persistence(client, db):
    goal = client.post("/api/goals", json={"title": "Learn C++"}).json()
    response = client.post("/api/tasks", json={"title": "Pointers", "goal_id": goal["id"]})
    assert response.status_code == 201
    identifier = response.json()["id"]
    assert client.patch(f"/api/tasks/{identifier}", json={"priority": 5}).json()["priority"] == 5
    with Session(db.bind) as restarted:
        assert restarted.scalar(select(Task)).title == "Pointers"
    assert client.patch(f"/api/tasks/{identifier}", json={"status": "completed"}).status_code == 200
    assert client.delete(f"/api/tasks/{identifier}").status_code == 204
    assert client.get("/api/tasks").json() == []
    assert client.delete(f"/api/tasks/{identifier}").status_code == 404


def test_validation_and_foreign_keys(client):
    assert (
        client.post("/api/tasks", json={"title": "Bad", "duration_minutes": 17}).status_code == 422
    )
    assert (
        client.post(
            "/api/tasks", json={"title": "Bad", "deadline": "2027-01-01T12:00:00"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tasks",
            json={"title": "Bad", "min_session_minutes": 90, "max_session_minutes": 30},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/tasks", json={"title": "Bad", "goal_id": "00000000-0000-0000-0000-000000000001"}
        ).status_code
        == 404
    )
    task = client.post("/api/tasks", json={"title": "Valid"}).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"priority": None}).status_code == 422
    assert client.get("/api/tasks").json()[0]["priority"] == 3


def test_preferences_and_obligations(client):
    prefs = client.get("/api/preferences").json()
    assert not prefs["monitoring_enabled"]
    assert (
        client.put("/api/preferences", json={**prefs, "timezone": "Invalid/Zone"}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/obligations",
            json={"title": "Class", "weekdays": [0, 2], "start_time": "13:00", "end_time": "15:00"},
        ).status_code
        == 201
    )
    assert client.get("/health").json() == {"status": "ok"}


def test_delete_goal_keeps_tasks(client):
    goal = client.post("/api/goals", json={"title": "Learn"}).json()
    client.post("/api/tasks", json={"title": "Practice", "goal_id": goal["id"]})
    assert client.delete(f"/api/goals/{goal['id']}").status_code == 204
    assert client.get("/api/tasks").json()[0]["goal_id"] is None

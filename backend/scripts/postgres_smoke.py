"""Real PostgreSQL persistence/migration smoke check, including a process boundary."""

import subprocess
import sys

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, engine
from app.main import app
from app.models import Goal, ScheduleSession, Task


def main():
    assert engine.dialect.name == "postgresql", "This check requires PostgreSQL"
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        created = client.post("/api/tasks", json={"title": "PostgreSQL persistence smoke"})
        assert created.status_code == 201, created.text
        identifier = created.json()["id"]
    # A separate interpreter simulates restarting the API process.
    code = (
        "from uuid import UUID; from app.db import SessionLocal; from app.models import Task; "
        f"db=SessionLocal(); assert db.get(Task, UUID('{identifier}')).title == "
        "'PostgreSQL persistence smoke'; db.close()"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    with TestClient(app) as client:
        assert client.delete(f"/api/tasks/{identifier}").status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(Goal.id)) is not None
        assert db.scalar(select(Task.id)) is not None
        assert db.scalar(select(ScheduleSession.id)) is not None
    print("PostgreSQL API, seeded schedule, foreign keys and cross-process persistence passed.")


if __name__ == "__main__":
    main()

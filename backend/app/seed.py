"""Optional sample data, idempotent and never destructive."""

from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import Goal
from app.schemas import GoalCreate, ObligationCreate, PlanRequest, TaskCreate
from app.services import resources
from app.services.scheduler import generate_plan


def seed():
    with SessionLocal.begin() as db:
        resources.preferences(db, lock=True)
        if db.scalar(select(Goal.id).limit(1)):
            print("Existing goals found; seed skipped. No data changed.")
            return
        goal = resources.create_goal(
            db,
            GoalCreate(
                title="Build confidence in C++",
                description="Demo goal: make steady progress through deliberate practice.",
                deadline=utcnow() + timedelta(days=60),
            ),
        )
        resources.create_task(
            db,
            TaskCreate(
                title="C++ foundations: memory and pointers",
                goal_id=goal.id,
                duration_minutes=180,
                activity_apps=["Code.exe", "devenv.exe"],
            ),
        )
        resources.create_task(
            db,
            TaskCreate(
                title="LeetCode practice", recurrence="daily", duration_minutes=60, priority=4
            ),
        )
        resources.create_task(
            db,
            TaskCreate(
                title="Programming assignment",
                duration_minutes=180,
                deadline=utcnow() + timedelta(days=3),
                priority=5,
            ),
        )
        resources.create_task(
            db, TaskCreate(title="Workout", recurrence="weekly", sessions_per_week=4)
        )
        resources.save_obligation(
            db,
            ObligationCreate(
                title="Computer science class",
                weekdays=[0, 2],
                start_time="13:00",
                end_time="15:00",
            ),
        )
        result = generate_plan(db, PlanRequest(days=7))
        print(f"Seeded sample goal, four tasks and a class. {result.explanation}")


if __name__ == "__main__":
    seed()

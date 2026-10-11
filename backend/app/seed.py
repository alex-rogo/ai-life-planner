"""Optional sample data, idempotent and never destructive."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import Goal
from app.schemas import GoalCreate, ObligationCreate, PlanRequest, TaskCreate
from app.services import resources
from app.services.scheduler import generate_plan

# Goals with their tasks. Titles keep the demo commands working: they refer to
# "C++", "LeetCode", "assignment" and "workout", each matching exactly one task.
GOALS = [
    (
        "Build confidence in C++",
        "Make steady progress through deliberate practice.",
        60,
        [
            dict(
                title="C++ foundations: memory and pointers",
                duration_minutes=180,
                activity_apps=["Code.exe", "devenv.exe"],
            ),
            dict(title="Practice project: text adventure", duration_minutes=240, priority=2),
        ],
    ),
    (
        "Launch portfolio site",
        "Ship the redesigned portfolio before applying to studios.",
        7,
        [
            dict(title="Portfolio: write case study", duration_minutes=180, priority=4),
            dict(title="Portfolio: export project images", duration_minutes=90, priority=4),
            dict(title="Portfolio: final copy edit", duration_minutes=60, priority=3),
        ],
    ),
    (
        "Conversational Spanish",
        "Hold a 20-minute conversation by spring.",
        120,
        [
            dict(
                title="Spanish practice",
                recurrence="daily",
                duration_minutes=30,
                category="personal",
            ),
        ],
    ),
    (
        "Half marathon in April",
        "Build up to 13.1 miles without injury.",
        180,
        [
            dict(
                title="Run",
                recurrence="weekly",
                sessions_per_week=3,
                duration_minutes=45,
                category="routine",
            ),
        ],
    ),
]

# Standalone tasks: (fields, deadline in days or None).
TASKS = [
    (
        dict(
            title="LeetCode practice",
            recurrence="daily",
            duration_minutes=60,
            priority=4,
            category="personal",
        ),
        None,
    ),
    (dict(title="Programming assignment", duration_minutes=180, priority=5), 3),
    (dict(title="Q4 budget review", duration_minutes=90, priority=5), 1),
    (
        dict(title="Workout", recurrence="weekly", sessions_per_week=4, category="routine"),
        None,
    ),
    (
        dict(
            title="Weekly review",
            recurrence="weekly",
            sessions_per_week=1,
            duration_minutes=30,
            priority=2,
        ),
        None,
    ),
    (dict(title="Pick up groceries", duration_minutes=30, category="errand"), 2),
    (dict(title="Call the landlord about the lease", duration_minutes=30, category="errand"), 4),
    (dict(title="Book flights for the holidays", duration_minutes=30, category="errand"), 6),
]

# Recurring fixed commitments: (title, kind, weekdays with Monday = 0, start, end).
RECURRING = [
    ("Computer science class", "commitment", [0, 2], "13:00", "15:00"),
    ("Team standup", "commitment", [0, 1, 2, 3, 4], "10:00", "10:15"),
    ("Climbing with Sam", "personal", [1], "19:00", "21:00"),
]

# One-off events: (days from today, title, kind, start, end). Times avoid the recurring blocks.
ONE_OFF = [
    (1, "Lunch with Maya", "personal", "12:00", "13:00"),
    (4, "Design interview · Lumen Studio", "interview", "11:00", "12:00"),
    (5, "Dentist cleaning", "appointment", "08:30", "09:30"),
    (9, "Recruiter call · Northwind", "interview", "16:00", "16:30"),
    (12, "Doctor check-up", "appointment", "15:30", "16:15"),
]


def add_sample_data(db) -> None:
    """Create the sample goals, tasks and events (without planning) in the open transaction."""
    now = utcnow()
    for title, description, days, tasks in GOALS:
        deadline = now + timedelta(days=days)
        goal = resources.create_goal(
            db, GoalCreate(title=title, description=description, deadline=deadline)
        )
        for fields in tasks:
            finite = fields.get("recurrence", "none") == "none"
            resources.create_task(
                db,
                TaskCreate(**fields, goal_id=goal.id, deadline=deadline if finite else None),
            )
    for fields, days in TASKS:
        deadline = now + timedelta(days=days) if days is not None else None
        resources.create_task(db, TaskCreate(**fields, deadline=deadline))
    for title, kind, weekdays, start, end in RECURRING:
        resources.save_obligation(
            db,
            ObligationCreate(
                title=title, kind=kind, weekdays=weekdays, start_time=start, end_time=end
            ),
        )
    today = now.astimezone(ZoneInfo(resources.preferences(db).timezone)).date()
    for offset, title, kind, start, end in ONE_OFF:
        day = today + timedelta(days=offset)
        if kind != "personal" and day.weekday() >= 5:
            # Interviews and appointments happen on weekdays.
            day += timedelta(days=7 - day.weekday())
        resources.save_obligation(
            db,
            ObligationCreate(
                title=title,
                kind=kind,
                weekdays=[day.weekday()],
                start_time=start,
                end_time=end,
                start_date=day,
                end_date=day,
            ),
        )


def seed():
    with SessionLocal.begin() as db:
        resources.preferences(db, lock=True)
        if db.scalar(select(Goal.id).limit(1)):
            print("Existing goals found; seed skipped. No data changed.")
            return
        add_sample_data(db)
        result = generate_plan(db, PlanRequest(days=7))
        print(
            f"Seeded {len(GOALS)} goals, "
            f"{sum(len(g[3]) for g in GOALS) + len(TASKS)} tasks and "
            f"{len(RECURRING) + len(ONE_OFF)} events. {result.explanation}"
        )


if __name__ == "__main__":
    seed()

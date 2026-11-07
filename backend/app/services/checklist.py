"""Checking off items in the sidebar's task list.

Each item has a stable key: ``task:<id>``, ``goal:<id>``, ``event:<id>`` (an imported deadline) or
``obligation:<id>:<date>`` (one occurrence of an appointment or interview). A one-off task is
finished for real, so Tomo stops planning it; everything else is only marked as done.
"""

import re
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import CheckedItem, ExternalEvent, Goal, Obligation, Task
from app.services.resources import require
from app.services.upkeep import replan

KEY = re.compile(
    r"^(task|goal|event|obligation):([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(?::(\d{4}-\d{2}-\d{2}))?$"
)
MODELS = {"task": Task, "goal": Goal, "event": ExternalEvent, "obligation": Obligation}


def key(kind: str, identifier: UUID, day: date | None = None) -> str:
    return f"{kind}:{identifier}" + (f":{day.isoformat()}" if day else "")


def checked(db: Session) -> set[str]:
    return set(db.scalars(select(CheckedItem.key)))


def set_done(db: Session, item: str, done: bool) -> None:
    match = KEY.match(item)
    if not match or (match[1] == "obligation") != bool(match[3]):
        raise HTTPException(422, "Unknown item. Refresh the page and try again.")
    kind, identifier = match[1], UUID(match[2])
    row = require(db, MODELS[kind], identifier)
    if kind == "task":
        if row.recurrence != "none":
            raise HTTPException(409, "Routines repeat, so they can't be checked off.")
        row.status = "completed" if done else "pending"
        db.flush()
        replan(db)
        return
    db.execute(delete(CheckedItem).where(CheckedItem.key == item))
    if done:
        db.add(CheckedItem(key=item))
    db.flush()

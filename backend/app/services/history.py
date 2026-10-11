"""Whole-plan snapshots for undoing an applied assistant proposal.

The app is single-user and its planning state is small, so a full copy of the planning
tables is simpler and safer than inverting each action.
"""

import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import Uuid, delete, insert, select, update
from sqlalchemy.orm import Session

from app.db import UTCDateTime
from app.models import Goal, Obligation, Preference, ScheduleSession, Suggestion, Task

# Parents before children; deletion runs in reverse.
MODELS = [Goal, Obligation, Task, ScheduleSession, Suggestion]
# Bookkeeping that must stay monotonic rather than travel back in time.
SKIP = {"planned_through"}


def _encode(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decode(column, value):
    if value is None:
        return None
    if isinstance(column.type, Uuid):
        return UUID(value)
    if isinstance(column.type, UTCDateTime):
        return datetime.fromisoformat(value)
    return value


def _rows(db: Session, table) -> list[dict]:
    rows = [
        {key: _encode(value) for key, value in row._mapping.items()}
        for row in db.execute(select(table))
    ]
    return sorted(rows, key=lambda row: str(row["id"]))


def snapshot(db: Session) -> dict:
    db.flush()
    data = {model.__tablename__: _rows(db, model.__table__) for model in MODELS}
    prefs = _rows(db, Preference.__table__)
    data["preferences"] = [{k: v for k, v in row.items() if k not in SKIP} for row in prefs]
    return data


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def restore(db: Session, data: dict) -> None:
    db.flush()
    for model in reversed(MODELS):
        db.execute(delete(model))
    for model in MODELS:
        table = model.__table__
        rows = [
            {key: _decode(table.c[key], value) for key, value in row.items()}
            for row in data[model.__tablename__]
        ]
        if rows:
            db.execute(insert(model), rows)
    table = Preference.__table__
    for row in data["preferences"]:
        values = {key: _decode(table.c[key], value) for key, value in row.items() if key != "id"}
        db.execute(update(Preference).where(Preference.id == row["id"]).values(**values))
    # Identity-map objects now describe rows that were replaced underneath them.
    db.expire_all()

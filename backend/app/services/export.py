"""Export the plan as an .ics file for Google Calendar, Apple Calendar or Outlook.

Fixed events and their trips are expanded for the requested weeks; flexible work (habits,
tasks) exists only as far ahead as Tomo has planned, normally about a week. Imported feed items
are left out by default: the user usually has those calendars elsewhere already, and copying them
would create duplicates.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ExternalEvent, Obligation, ScheduleSession
from app.services.resources import preferences
from app.services.scheduler import expand_obligations, local_midnight, travel_blocks
from app.services.upkeep import session_views

LABEL = {"focus": "Focus", "routine": "Routine", "personal": "Personal", "errand": "Errand"}


def _event(uid: str, title: str, start: datetime, end: datetime, note: str = "") -> icalendar.Event:
    event = icalendar.Event()
    event.add("uid", f"{uid}@tomo")
    event.add("summary", title)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", utcnow())
    if note:
        event.add("description", note)
    return event


def build(db: Session, weeks: int, imported: bool, now: datetime | None = None) -> bytes:
    now = now or utcnow()
    tz = ZoneInfo(preferences(db).timezone)
    today: date = now.astimezone(tz).date()
    start, end = local_midnight(today, tz), local_midnight(today + timedelta(weeks=weeks), tz)
    calendar = icalendar.Calendar()
    calendar.add("prodid", "-//Tomo//Planner export//EN")
    calendar.add("version", "2.0")
    calendar.add("x-wr-calname", "Tomo")
    calendar.add("x-wr-timezone", tz.key)

    # Fixed events and their trips, for the whole range (computed, not only what's been planned).
    obligations = db.scalars(select(Obligation)).all()
    for row in expand_obligations(obligations, start, end, tz) + travel_blocks(
        obligations, start, end, tz
    ):
        kind = "trip" if row.travel else "event"
        calendar.add_component(
            _event(
                f"{kind}-{row.obligation_id}-{row.starts_at:%Y%m%dT%H%M}",
                row.title,
                row.starts_at,
                row.ends_at,
                "Travel" if row.travel else "Fixed commitment",
            )
        )

    # Flexible work Tomo has planned (habits and tasks).
    planned = db.scalars(
        select(ScheduleSession).where(
            ScheduleSession.task_id.is_not(None),
            ScheduleSession.status.in_(("planned", "completed")),
            ScheduleSession.ends_at > start,
            ScheduleSession.starts_at < end,
        )
    ).all()
    for view in session_views(db, planned):
        note = LABEL.get(view["category"], "")
        if view.get("subtitle"):
            note = f"{note} · {view['subtitle']}" if note else view["subtitle"]
        calendar.add_component(
            _event(
                f"session-{view['id']}",
                view["title"],
                datetime.fromisoformat(view["starts_at"]),
                datetime.fromisoformat(view["ends_at"]),
                note,
            )
        )

    if imported:
        for item in db.scalars(
            select(ExternalEvent).where(
                ExternalEvent.starts_at < end, ExternalEvent.ends_at >= start
            )
        ):
            course = f" [{item.course}]" if item.course else ""
            if item.kind == "all_day":
                event = _event(
                    f"imported-{item.id}",
                    f"{item.title}{course}",
                    item.starts_at.astimezone(tz).date(),
                    item.ends_at.astimezone(tz).date(),
                )
            else:
                # Deadlines are moments; show them as a short block ending at the due time.
                begins = (
                    item.starts_at - timedelta(minutes=15)
                    if item.kind == "deadline"
                    else item.starts_at
                )
                event = _event(
                    f"imported-{item.id}",
                    f"Due: {item.title}{course}"
                    if item.kind == "deadline"
                    else f"{item.title}{course}",
                    begins,
                    item.ends_at if item.ends_at > item.starts_at else item.starts_at,
                    item.location,
                )
            calendar.add_component(event)
    return calendar.to_ical()

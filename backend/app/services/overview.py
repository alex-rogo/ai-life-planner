"""Summaries for the planner screen: what's coming up, goal progress, stats and briefs."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import ExternalEvent, Goal, Obligation, ScheduleSession, Task
from app.services.ai.interpreter import DEMO_COMMANDS
from app.services.resources import preferences
from app.services.scheduler import clock_minutes, local_midnight
from app.services.upkeep import occurrences, sessions_between

UPCOMING_DAYS = 21
KINDS = {"appointment": "Appointment", "interview": "Interview", "personal": "Personal"}
PROMPTS = [
    "I'm wiped — lighten today",
    "Keep this evening free",
    "Reschedule my week",
]


def _minutes(session: ScheduleSession) -> int:
    return int((session.ends_at - session.starts_at).total_seconds() // 60)


def span(minutes: int) -> str:
    hours, rest = divmod(max(0, minutes), 60)
    if hours and rest:
        return f"{hours}h {rest:02d}m"
    return f"{hours}h" if hours else f"{rest}m"


def _clock(stamp: datetime, tz: ZoneInfo) -> str:
    return stamp.astimezone(tz).strftime("%I:%M %p").lstrip("0").lower()


def _when(day: date, today: date) -> str:
    gap = (day - today).days
    return "today" if gap == 0 else "tomorrow" if gap == 1 else f"in {gap} days"


def unscheduled_minutes(task: Task, sessions: list[ScheduleSession], now: datetime) -> int:
    """One-time work still neither done nor booked before its deadline."""
    if task.recurrence != "none" or task.status != "pending":
        return 0
    booked = sum(
        _minutes(s)
        for s in sessions
        if s.task_id == task.id
        and s.status == "planned"
        and s.ends_at > now
        and (not task.deadline or s.ends_at <= task.deadline)
    )
    return max(0, task.duration_minutes - task.completed_minutes - booked)


def _upcoming(db, tasks, goals, sessions, today, tz, now, externals):
    last = today + timedelta(days=UPCOMING_DAYS)
    items = []
    for obligation in db.scalars(select(Obligation).where(Obligation.kind != "commitment")):
        for day in list(occurrences(obligation, today, last))[:1]:
            start = clock_minutes(obligation.start_time)
            stamp = local_midnight(day, tz) + timedelta(minutes=start)
            length = clock_minutes(obligation.end_time) - start
            if stamp + timedelta(minutes=length) <= now:
                continue
            items.append(
                {
                    "kind": KINDS[obligation.kind],
                    "date": day,
                    "when": _when(day, today),
                    "title": obligation.title,
                    "meta": f"{_clock(stamp, tz)} · {span(length)}",
                    "note": "",
                    "obligation_id": obligation.id,
                }
            )
    for goal in goals:
        if not goal.deadline or goal.deadline < now:
            continue
        day = goal.deadline.astimezone(tz).date()
        if day > last:
            continue
        own = [t for t in tasks if t.goal_id == goal.id and t.status != "cancelled"]
        left = [t for t in own if t.status == "pending"]
        gap = sum(unscheduled_minutes(t, sessions, now) for t in own)
        items.append(
            {
                "kind": "Project",
                "date": day,
                "when": _when(day, today),
                "title": goal.title,
                "meta": f"{len(left)} tasks left · " + ("on track" if not gap else "behind"),
                "note": f"Needs {span(gap)} · not scheduled" if gap else "",
                "goal_id": goal.id,
            }
        )
    for task in tasks:
        if task.goal_id or not task.deadline or task.deadline < now or task.status != "pending":
            continue
        day = task.deadline.astimezone(tz).date()
        if day > last:
            continue
        gap = unscheduled_minutes(task, sessions, now)
        left = task.duration_minutes - task.completed_minutes
        items.append(
            {
                "kind": "Project",
                "date": day,
                "when": _when(day, today),
                "title": task.title,
                "meta": f"Due {_clock(task.deadline, tz)} · {span(left)} of work left",
                "note": f"Needs {span(gap)} · not scheduled" if gap else "",
            }
        )
    for event in externals:
        # Assignments from connected calendars (Canvas) are fixed deadlines.
        day = event.starts_at.astimezone(tz).date()
        if event.kind != "deadline" or event.starts_at < now or day > last:
            continue
        course = f" · {event.course}" if event.course else ""
        items.append(
            {
                "kind": "Assignment",
                "date": day,
                "when": _when(day, today),
                "title": event.title,
                "meta": f"Due {_clock(event.starts_at, tz)}{course}",
                "note": "",
            }
        )
    return sorted(items, key=lambda item: item["date"])


def _goal_progress(goals, tasks, window, days, tz):
    rows = []
    for goal in goals:
        own = [t for t in tasks if t.goal_id == goal.id and t.status != "cancelled"]
        local = goal.deadline.astimezone(tz) if goal.deadline else None
        due = f"due {local:%b} {local.day}" if local else "no deadline"
        if days > 1:
            # Week view: sessions finished out of sessions booked in the visible range.
            ids = {t.id for t in own}
            mine = [s for s in window if s.task_id in ids and s.status in ("planned", "completed")]
            finished = sum(s.status == "completed" for s in mine)
            pct = round(100 * finished / len(mine)) if mine else 0
            progress = f"{finished} / {len(mine)}"
            meta = f"Sessions {'this week' if days == 7 else 'in view'} · {due}"
        else:
            finite = [t for t in own if t.recurrence == "none"]
            total = sum(t.duration_minutes for t in finite)
            done = sum(min(t.completed_minutes, t.duration_minutes) for t in finite)
            pct = round(100 * done / total) if total else 0
            finished = sum(t.status == "completed" for t in own)
            progress = f"{pct}%"
            meta = f"{due[0].upper()}{due[1:]} · {finished} of {len(own)} tasks"
        rows.append(
            {"id": goal.id, "title": goal.title, "pct": pct, "progress": progress, "meta": meta}
        )
    return rows


def _free_minutes(prefs, day, sessions, tz, now) -> int:
    begin = local_midnight(day, tz) + timedelta(minutes=clock_minutes(prefs.available_start))
    end = local_midnight(day, tz) + timedelta(minutes=clock_minutes(prefs.available_end))
    begin = max(begin, now)
    if end <= begin:
        return 0
    booked = sum(
        max(0, (min(s.ends_at, end) - max(s.starts_at, begin)).total_seconds() // 60)
        for s in sessions
        if s.status in ("planned", "completed")
    )
    return int((end - begin).total_seconds() // 60 - booked)


def build(db: Session, start: date, days: int, settings: Settings) -> dict:
    now = utcnow()
    prefs = preferences(db)
    tz = ZoneInfo(prefs.timezone)
    today = now.astimezone(tz).date()
    begin, end = local_midnight(start, tz), local_midnight(start + timedelta(days=days), tz)
    tasks = db.scalars(select(Task).order_by(Task.created_at)).all()
    goals = db.scalars(select(Goal).order_by(Goal.created_at)).all()
    horizon = local_midnight(today + timedelta(days=UPCOMING_DAYS + 1), tz)
    sessions = sessions_between(db, min(begin, local_midnight(today, tz)), max(end, horizon))
    externals = db.scalars(
        select(ExternalEvent).where(
            ExternalEvent.starts_at < max(end, horizon),
            ExternalEvent.ends_at >= min(begin, local_midnight(today, tz)),
        )
    ).all()
    # Timed events from connected calendars count as fixed commitments in every stat.
    busy = [
        SimpleNamespace(
            starts_at=e.starts_at,
            ends_at=e.ends_at,
            title=e.title,
            status="planned",
            task_id=None,
            credited_minutes=0,
        )
        for e in externals
        if e.kind == "event"
    ]
    window = [s for s in [*sessions, *busy] if s.ends_at > begin and s.starts_at < end]
    live = [s for s in window if s.status in ("planned", "completed")]
    category = {t.id: t.category for t in tasks}

    if days == 1:
        left = [s for s in live if s.status == "planned" and s.ends_at > now]
        free = _free_minutes(prefs, start, live, tz, now)
        behind = any(
            unscheduled_minutes(t, sessions, now)
            and t.deadline
            and t.deadline.astimezone(tz).date() <= start + timedelta(days=1)
            for t in tasks
        )
        # Little free time is expected once the day is nearly over; that is not an overbooked plan.
        remaining = _free_minutes(prefs, start, [], tz, now)
        if behind:
            health = "Tight"
        elif start == today and remaining < 120:
            health = "Wrapping up"
        else:
            health = "Tight" if free < 30 else "Relaxed" if free >= 180 else "Realistic"
        count = f"{len(left)} block{'' if len(left) == 1 else 's'}"
        stats = [
            {"label": "Left today" if start == today else "Blocks", "value": count},
            {"label": "Free time", "value": span(free)},
            {"label": "Plan health", "value": health},
        ]
        label = f"{start:%B} {start.day}"
        mood = {
            "Tight": "it's a full day.",
            "Relaxed": "plenty of room.",
            "Realistic": "you're on track.",
            "Wrapping up": "the day's winding down.",
        }
        headline = f"{label} — {mood[health]}" if start >= today else label
        fixed_today = [s for s in live if not s.task_id and s.ends_at > now]
        due = [
            t
            for t in tasks
            if t.status == "pending" and t.deadline and t.deadline.astimezone(tz).date() == start
        ]
        parts = []
        if fixed_today:
            names = " and ".join(f"{_clock(s.starts_at, tz)} {s.title}" for s in fixed_today[:2])
            parts.append(f"I planned around your {names}.")
        else:
            parts.append("Nothing fixed on the calendar, so the day is yours to shape.")
        for task in due[:1]:
            slot = next((s for s in left if s.task_id == task.id), None)
            where = f", so it sits in your {_clock(slot.starts_at, tz)} block" if slot else ""
            parts.append(f"{task.title} is due today{where}.")
        parts.append(f"You have {span(free)} of open time.")
        brief = " ".join(parts)
        summary = ""
    else:
        focus = sum(_minutes(s) for s in live if s.task_id and category.get(s.task_id) == "focus")
        commitments = sum(_minutes(s) for s in live if not s.task_id)
        evenings = 0
        for offset in range(days):
            day = start + timedelta(days=offset)
            evening = local_midnight(day, tz) + timedelta(hours=18)
            night = local_midnight(day + timedelta(days=1), tz)
            if not any(s.starts_at < night and s.ends_at > evening for s in live):
                evenings += 1
        stats = [
            {"label": "Focus time", "value": span(focus)},
            {"label": "Commitments", "value": span(commitments)},
            {"label": "Free evenings", "value": f"{evenings} of {days}"},
        ]
        last = start + timedelta(days=days - 1)
        headline = (
            f"{start:%B} {start.day} – {last.day}"
            if start.month == last.month
            else f"{start:%B} {start.day} – {last:%B} {last.day}"
        )
        done = sum(s.credited_minutes for s in window if s.status == "completed" and s.task_id)
        gap = sum(unscheduled_minutes(t, sessions, now) for t in tasks)
        summary = f"{span(done)} of work done so far, {span(focus)} of focus time planned."
        period = "this week" if days == 7 else "in this view"
        brief = f"You've put {span(done)} into planned work so far {period}."
        later = [
            s for s in sessions if not s.task_id and s.starts_at >= end and s.status == "planned"
        ]
        if later:
            names = " and ".join(f"{s.title} ({s.starts_at.astimezone(tz):%a})" for s in later[:2])
            brief += f" {'Next week' if days == 7 else 'After that'} brings {names}."
        if gap:
            brief += f" {span(gap)} of deadline work isn't scheduled yet."
            summary += f" {span(gap)} of deadline work still needs a slot."
        else:
            summary += " Every deadline has time booked."

    deadlines = []
    for task in tasks:
        if task.status == "pending" and task.deadline and begin <= task.deadline < end:
            deadlines.append({"date": task.deadline.astimezone(tz).date(), "title": task.title})
    for goal in goals:
        if goal.deadline and begin <= goal.deadline < end:
            deadlines.append(
                {"date": goal.deadline.astimezone(tz).date(), "title": goal.title, "kind": "goal"}
            )
    for event in externals:
        if event.kind != "event" and begin <= event.starts_at < end:
            kind = "assignment" if event.kind == "deadline" else "all_day"
            deadlines.append(
                {"date": event.starts_at.astimezone(tz).date(), "title": event.title, "kind": kind}
            )

    # The visible hour range covers availability plus anything booked outside it.
    first = clock_minutes(prefs.available_start) // 60
    last_hour = -(-clock_minutes(prefs.available_end) // 60)
    for s in live:
        local_start, local_end = s.starts_at.astimezone(tz), s.ends_at.astimezone(tz)
        first = min(first, local_start.hour)
        if local_end.date() == local_start.date():
            last_hour = max(last_hour, local_end.hour + (local_end.minute > 0))
    prompts = DEMO_COMMANDS[4:6] + DEMO_COMMANDS[-1:] if settings.ai_mode == "demo" else PROMPTS
    return {
        "timezone": prefs.timezone,
        "start": start,
        "days": days,
        "headline": headline,
        "summary": summary,
        "brief": brief,
        "stats": stats,
        "upcoming": _upcoming(db, tasks, goals, sessions, today, tz, now, externals),
        "goals": _goal_progress(goals, tasks, window, days, tz),
        "deadlines": sorted(deadlines, key=lambda d: d["date"]),
        "prompts": prompts,
        "first_hour": max(0, first),
        "last_hour": min(24, max(last_hour, first + 1)),
    }

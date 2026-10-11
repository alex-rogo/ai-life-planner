"""Calendar feed subscriptions (.ics): Canvas, Google, Outlook, Apple or any other feed.

Imported items are read-only and fixed. Timed events block planning like obligations but may
overlap anything; zero-length items (Canvas assignments) are deadlines; date-only items are
all-day notes. Network access happens before any database lock is taken.
"""

import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import CalendarSource, ExternalEvent
from app.services.resources import preferences

PAST_DAYS, FUTURE_DAYS = 14, 60
STALE = timedelta(minutes=15)
MAX_BYTES = 5_000_000
DEMO_URL = "demo://canvas"
# Canvas titles end with the course in brackets: "Lab 4: Hash tables [CS 241]".
COURSE = re.compile(r"^(?P<title>.*?)\s*\[(?P<course>[^\[\]]{1,120})\]\s*$")
FIELDS = ("kind", "title", "course", "location", "starts_at", "ends_at")


def normalize_url(url: str) -> str:
    url = url.strip()
    if url == DEMO_URL:
        return url
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://") :]
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            422, "Paste the calendar's feed link (it starts with https:// or webcal://)."
        )
    return url


def url_hint(url: str) -> str:
    """Enough to recognise a feed without revealing its secret token."""
    if url == DEMO_URL:
        return "Built-in demo feed"
    return f"{urlparse(url).netloc} · …{url[-4:]}"


def _download(url: str) -> str:
    try:
        with (
            httpx.Client(
                timeout=15,
                follow_redirects=True,
                max_redirects=5,
                headers={"User-Agent": "Tomo calendar sync", "Accept": "text/calendar, */*"},
            ) as client,
            client.stream("GET", url) as response,
        ):
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HTTPException(422, "That calendar feed is larger than 5 MB.")
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hint = " The link may have been reset; copy it again." if status in (401, 403, 404) else ""
        raise HTTPException(502, f"The calendar feed answered with HTTP {status}.{hint}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, "Couldn't reach the calendar feed. Check the link and connection."
        ) from exc
    return body.decode("utf-8", errors="replace")


def _aware(value: datetime, tz: ZoneInfo) -> datetime:
    # Floating times (no zone) are local wall-clock times in the user's timezone.
    return value.replace(tzinfo=tz) if value.tzinfo is None else value


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(), tzinfo=tz)


def parse(text: str, now: datetime, tz: ZoneInfo) -> list[dict]:
    """Calendar items in the import window, one per occurrence of repeating events."""
    try:
        calendar = icalendar.Calendar.from_ical(text)
    except ValueError as exc:
        raise HTTPException(422, "That link didn't return a calendar feed (.ics).") from exc
    today = now.astimezone(tz).date()
    window = (today - timedelta(days=PAST_DAYS), today + timedelta(days=FUTURE_DAYS))
    try:
        events = list(recurring_ical_events.of(calendar).between(*window))
    except Exception as exc:  # malformed repeat rules and the like
        raise HTTPException(422, "The calendar feed couldn't be read.") from exc
    uids = Counter(str(e.get("UID", "")) for e in events)
    items = []
    for event in events:
        if str(event.get("STATUS", "")).upper() == "CANCELLED" or not event.get("DTSTART"):
            continue
        uid = str(event.get("UID", "")) or f"untitled-{len(items)}"
        start = event["DTSTART"].dt
        end = event["DTEND"].dt if event.get("DTEND") else None
        if not isinstance(start, datetime):  # date-only: an all-day item
            last = (
                end
                if isinstance(end, date) and not isinstance(end, datetime) and end > start
                else start + timedelta(days=1)
            )
            starts_at, ends_at = _local_midnight(start, tz), _local_midnight(last, tz)
            kind = "deadline" if uid.startswith("event-assignment-") else "all_day"
        else:
            starts_at = _aware(start, tz)
            if isinstance(end, datetime):
                ends_at = _aware(end, tz)
            elif event.get("DURATION"):
                ends_at = starts_at + event["DURATION"].dt
            else:
                ends_at = starts_at
            # Canvas assignments are zero-length items at their due time.
            deadline = uid.startswith("event-assignment-") or ends_at <= starts_at
            kind = "deadline" if deadline else "event"
            if deadline:
                ends_at = starts_at
        summary = " ".join(str(event.get("SUMMARY", "Untitled")).split()) or "Untitled"
        match = COURSE.match(summary)
        title, course = (
            (match["title"], match["course"]) if match and match["title"] else (summary, None)
        )
        items.append(
            {
                # Repeating events share a UID; each occurrence is identified by its start.
                "uid": (uid if uids[uid] == 1 else f"{uid}|{starts_at.isoformat()}")[:400],
                "kind": kind,
                "title": title[:300],
                "course": course,
                "location": " ".join(str(event.get("LOCATION", "")).split())[:300],
                "starts_at": starts_at,
                "ends_at": ends_at,
            }
        )
    return items


def pull(url: str, now: datetime, tz: ZoneInfo) -> list[dict]:
    """Fetch and parse a feed. No database access, so callers do this before locking."""
    return parse(demo_feed(now, tz) if url == DEMO_URL else _download(url), now, tz)


def store(db: Session, source: CalendarSource, items: list[dict], now: datetime) -> bool:
    """Make the source's events match the feed, keeping row ids for unchanged items."""
    existing = {
        e.uid: e
        for e in db.scalars(select(ExternalEvent).where(ExternalEvent.source_id == source.id))
    }
    changed = False
    for item in items:
        row = existing.pop(item["uid"], None)
        if row is None:
            db.add(ExternalEvent(source_id=source.id, **item))
            changed = True
        elif any(getattr(row, f) != item[f] for f in FIELDS):
            for f in FIELDS:
                setattr(row, f, item[f])
            changed = True
    for row in existing.values():
        db.delete(row)
        changed = True
    source.last_synced_at, source.last_error = now, ""
    db.flush()
    return changed


def stale_sources(db: Session, now: datetime) -> list[CalendarSource]:
    return [
        s
        for s in db.scalars(select(CalendarSource).order_by(CalendarSource.created_at))
        if not s.last_synced_at or now - s.last_synced_at >= STALE
    ]


def timezone(db: Session) -> ZoneInfo:
    return ZoneInfo(preferences(db).timezone)


def demo_feed(now: datetime, tz: ZoneInfo) -> str:
    """A realistic Canvas-style feed around `now`: weekly lectures, assignments, an exam."""
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday())
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    def local(day: date, clock: str) -> str:
        return f"{day:%Y%m%d}T{clock.replace(':', '')}00"

    def utc(day: date, clock: str) -> str:
        moment = datetime.combine(day, time.fromisoformat(clock), tzinfo=tz).astimezone(
            ZoneInfo("UTC")
        )
        return moment.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Instructure//Canvas demo//EN",
        "X-WR-CALNAME:Canvas (demo)",
    ]

    def event(uid: str, summary: str, extra: list[str]):
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"SUMMARY:{summary}",
                *extra,
                "END:VEVENT",
            ]
        )

    lectures = [
        (
            "lec-math",
            "Linear Algebra lecture [MATH 221]",
            "MO,WE,FR",
            "09:00",
            "09:50",
            "Hall B 120",
        ),
        (
            "lec-cs",
            "Data Structures lecture [CS 241]",
            "TU,TH",
            "16:00",
            "17:15",
            "Engineering 210",
        ),
        ("lec-eng", "Academic Writing seminar [ENG 105]", "TH", "18:00", "19:15", "Humanities 3"),
    ]
    for uid, summary, days, start, end, room in lectures:
        first = monday - timedelta(days=7)
        event(
            f"event-calendar-event-{uid}",
            summary,
            [
                f"DTSTART;TZID={tz.key}:{local(first, start)}",
                f"DTEND;TZID={tz.key}:{local(first, end)}",
                f"RRULE:FREQ=WEEKLY;BYDAY={days};COUNT=36",
                f"LOCATION:{room}",
            ],
        )
    assignments = [
        (0, "23:59", "Reading response 5 [ENG 105]"),
        (1, "23:59", "Lab 4: Hash tables [CS 241]"),
        (2, "23:59", "Problem set 6 [MATH 221]"),
        (3, "23:59", "Essay draft: Rhetorical analysis [ENG 105]"),
        (4, "10:00", "Quiz 5 [MATH 221]"),
        (8, "23:59", "Project milestone 2 [CS 241]"),
        (9, "23:59", "Problem set 7 [MATH 221]"),
        (16, "23:59", "Final essay [ENG 105]"),
    ]
    for i, (offset, clock, summary) in enumerate(assignments):
        day = today + timedelta(days=offset)
        moment = utc(day, clock)
        event(f"event-assignment-{9100 + i}", summary, [f"DTSTART:{moment}", f"DTEND:{moment}"])
    exam = today + timedelta(days=7)
    event(
        "event-calendar-event-midterm",
        "Midterm exam [MATH 221]",
        [f"DTSTART:{utc(exam, '18:00')}", f"DTEND:{utc(exam, '20:00')}", "LOCATION:Hall B 120"],
    )
    holiday = today + timedelta(days=5)
    event(
        "event-calendar-event-break",
        "No classes: campus holiday",
        [
            f"DTSTART;VALUE=DATE:{holiday:%Y%m%d}",
            f"DTEND;VALUE=DATE:{holiday + timedelta(days=1):%Y%m%d}",
        ],
    )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


NAMES = {
    "canvas": "Canvas",
    "google": "Google Calendar",
    "outlook": "Outlook",
    "apple": "Apple Calendar",
    "other": "Calendar",
    "demo": "Canvas (demo)",
}


def require_source(db: Session, identifier) -> CalendarSource:
    row = db.get(CalendarSource, identifier)
    if row is None:
        raise HTTPException(404, "Calendar not found")
    return row


def out(db: Session, source: CalendarSource) -> dict:
    kinds = Counter(
        db.scalars(select(ExternalEvent.kind).where(ExternalEvent.source_id == source.id))
    )
    return {
        "id": source.id,
        "name": source.name,
        "provider": source.provider,
        "url_hint": url_hint(source.url),
        "last_synced_at": source.last_synced_at,
        "last_error": source.last_error,
        "events": kinds["event"],
        "deadlines": kinds["deadline"],
        "all_day": kinds["all_day"],
    }


def _settled(db: Session) -> tuple[datetime, ZoneInfo]:
    """Current time and zone, ending the read transaction so no lock is held over the network."""
    now, tz = utcnow(), timezone(db)
    db.commit()
    return now, tz


def _replan(db: Session) -> None:
    from app.services.upkeep import replan

    try:
        replan(db)
    except HTTPException:
        # Conflicts are reported on the next change; the imported events are still saved.
        pass


def connect(db: Session, provider: str, name: str, url: str) -> dict:
    url = normalize_url(url)
    if (provider == "demo") != (url == DEMO_URL):
        raise HTTPException(422, "Paste the calendar's feed link.")
    now, tz = _settled(db)
    items = pull(url, now, tz)
    preferences(db, lock=True)
    source = CalendarSource(name=name.strip() or NAMES[provider], provider=provider, url=url)
    db.add(source)
    db.flush()
    store(db, source, items, now)
    _replan(db)
    return out(db, source)


def sync(db: Session, source: CalendarSource) -> dict:
    """Refresh one feed. A failed fetch is recorded on the source rather than raised."""
    identifier = source.id
    now, tz = _settled(db)
    try:
        items, error = pull(source.url, now, tz), ""
    except HTTPException as exc:
        items, error = None, str(exc.detail)
    preferences(db, lock=True)
    source = require_source(db, identifier)
    if items is None:
        source.last_synced_at, source.last_error = now, error
        db.flush()
    elif store(db, source, items, now):
        _replan(db)
    return out(db, source)


def sync_stale(db: Session) -> None:
    """Refresh feeds not synced for a while; called when the planner loads."""
    for source in stale_sources(db, utcnow()):
        sync(db, source)


def disconnect(db: Session, source: CalendarSource) -> None:
    preferences(db, lock=True)
    db.delete(source)
    db.flush()
    _replan(db)

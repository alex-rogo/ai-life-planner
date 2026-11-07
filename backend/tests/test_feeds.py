from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import CalendarSource, ExternalEvent
from app.services import feeds

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2027, 1, 4, 16, 0, tzinfo=UTC)  # Monday 08:00 Los Angeles

FEED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:event-assignment-501
DTSTAMP:20270101T000000Z
SUMMARY:Lab 4: Hash tables [CS 241]
DTSTART:20270106T075900Z
DTEND:20270106T075900Z
END:VEVENT
BEGIN:VEVENT
UID:event-calendar-event-lecture
DTSTAMP:20270101T000000Z
SUMMARY:Lecture [MATH 221]
DTSTART;TZID=America/Los_Angeles:20270104T090000
DTEND;TZID=America/Los_Angeles:20270104T095000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4
EXDATE;TZID=America/Los_Angeles:20270106T090000
LOCATION:Hall B
END:VEVENT
BEGIN:VEVENT
UID:holiday
DTSTAMP:20270101T000000Z
SUMMARY:Campus holiday
DTSTART;VALUE=DATE:20270108
DTEND;VALUE=DATE:20270109
END:VEVENT
BEGIN:VEVENT
UID:floating
DTSTAMP:20270101T000000Z
SUMMARY:Dinner
DTSTART:20270105T190000
DTEND:20270105T203000
END:VEVENT
BEGIN:VEVENT
UID:cancelled
DTSTAMP:20270101T000000Z
SUMMARY:Called off
STATUS:CANCELLED
DTSTART:20270105T170000Z
DTEND:20270105T180000Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_canvas_assignments_repeats_all_day_and_floating_times():
    items = {i["uid"]: i for i in feeds.parse(FEED, NOW, TZ)}
    lab = items["event-assignment-501"]
    assert (lab["kind"], lab["title"], lab["course"]) == (
        "deadline",
        "Lab 4: Hash tables",
        "CS 241",
    )
    assert lab["starts_at"] == lab["ends_at"]
    lectures = sorted(
        (i for i in items.values() if i["title"] == "Lecture"), key=lambda i: i["starts_at"]
    )
    # Four weekly occurrences minus the excluded Wednesday, each with its own identity.
    assert len(lectures) == 3
    assert len({i["uid"] for i in lectures}) == 3
    assert lectures[0]["starts_at"].astimezone(TZ).strftime("%a %H:%M") == "Mon 09:00"
    assert lectures[0]["course"] == "MATH 221" and lectures[0]["location"] == "Hall B"
    assert items["holiday"]["kind"] == "all_day"
    assert items["floating"]["starts_at"].astimezone(TZ).hour == 19
    assert "cancelled" not in items


def test_store_keeps_ids_updates_changes_and_drops_vanished_items(db):
    source = CalendarSource(name="Canvas", provider="canvas", url="https://school.example/feed.ics")
    db.add(source)
    db.flush()
    items = feeds.parse(FEED, NOW, TZ)
    assert feeds.store(db, source, items, NOW)
    ids = {e.uid: e.id for e in db.scalars(select(ExternalEvent))}
    assert not feeds.store(db, source, items, NOW)
    moved = [dict(i) for i in items if i["uid"] != "holiday"]
    lab = next(i for i in moved if i["uid"] == "event-assignment-501")
    lab["starts_at"] = lab["ends_at"] = lab["starts_at"] + timedelta(days=1)
    assert feeds.store(db, source, moved, NOW)
    after = {e.uid: e for e in db.scalars(select(ExternalEvent))}
    assert "holiday" not in after
    assert after["event-assignment-501"].id == ids["event-assignment-501"]
    assert after["event-assignment-501"].starts_at == lab["starts_at"]


def test_urls_are_validated_and_never_returned(client):
    bad = client.post(
        "/api/calendars", json={"provider": "canvas", "url": "ftp://example.com/x.ics"}
    )
    assert bad.status_code == 422
    assert client.get("/api/calendars").json() == []
    hint = feeds.url_hint("https://canvas.example.edu/feeds/calendars/user_SECRETTOKEN.ics")
    assert "SECRETTOKEN" not in hint and hint.startswith("canvas.example.edu")
    assert feeds.normalize_url("webcal://p01.icloud.com/x.ics") == "https://p01.icloud.com/x.ics"


def test_unreachable_feed_is_not_saved_and_sync_failures_are_recorded(client, monkeypatch):
    def offline(url):
        raise HTTPException(502, "Couldn't reach the calendar feed.")

    monkeypatch.setattr(feeds, "_download", offline)
    response = client.post(
        "/api/calendars", json={"provider": "google", "url": "https://calendar.example/basic.ics"}
    )
    assert response.status_code == 502
    assert client.get("/api/calendars").json() == []

    monkeypatch.setattr(feeds, "_download", lambda url: FEED)
    created = client.post(
        "/api/calendars", json={"provider": "google", "url": "https://calendar.example/basic.ics"}
    ).json()
    assert created["name"] == "Google Calendar" and created["last_error"] == ""
    monkeypatch.setattr(feeds, "_download", offline)
    synced = client.post(f"/api/calendars/{created['id']}/sync").json()
    assert "reach" in synced["last_error"]


def test_demo_canvas_feed_shows_fixed_blocks_deadlines_and_planning_avoids_it(client):
    response = client.post("/api/calendars", json={"provider": "demo", "url": feeds.DEMO_URL})
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["name"] == "Canvas (demo)"
    assert source["events"] and source["deadlines"] == 8 and source["all_day"] == 1
    assert "url" not in source

    task = client.post("/api/tasks", json={"title": "Study block", "duration_minutes": 600}).json()
    sessions = client.get("/api/sessions").json()
    external = [s for s in sessions if s["external"]]
    assert external and all(s["locked"] and s["category"] == "fixed" for s in external)
    assert {s["subtitle"] for s in external} >= {"MATH 221", "CS 241"}
    planned = [s for s in sessions if s["task_id"] == task["id"]]
    assert planned
    for work in planned:
        for event in external:
            assert work["ends_at"] <= event["starts_at"] or work["starts_at"] >= event["ends_at"]

    week = client.get("/api/overview", params={"days": 7}).json()
    assert {"assignment", "all_day"} <= {d["kind"] for d in week["deadlines"]}
    upcoming = [
        u for u in client.get("/api/overview").json()["upcoming"] if u["kind"] == "Assignment"
    ]
    assert upcoming and upcoming[0]["meta"].startswith("Due ")
    assert client.get("/api/system").json()["calendars"][0]["name"] == "Canvas (demo)"

    assert client.delete(f"/api/calendars/{source['id']}").status_code == 204
    assert not [s for s in client.get("/api/sessions").json() if s["external"]]


def test_demo_feed_requires_the_demo_provider(client):
    response = client.post("/api/calendars", json={"provider": "canvas", "url": feeds.DEMO_URL})
    assert response.status_code == 422
    with pytest.raises(HTTPException):
        feeds.parse("not a calendar", NOW, TZ)


def test_date_only_canvas_assignments_are_due_at_1159_pm_and_stay_listed_all_day(db):
    from app.services.overview import _upcoming

    extra = [
        "BEGIN:VEVENT",
        "UID:event-assignment-777",
        "DTSTAMP:20270101T000000Z",
        "SUMMARY:Exercise - Binary Search [CS 341]",
        "DTSTART;VALUE=DATE:20270104",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:event-assignment-778",
        "DTSTAMP:20270101T000000Z",
        "SUMMARY:Quiz 2 [CS 341]",
        "DTSTART:20270104T170000Z",
        "DTEND:20270104T170000Z",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    feed = FEED.replace("END:VCALENDAR", "\n".join(extra))
    items = {i["title"]: i for i in feeds.parse(feed, NOW, TZ)}
    binary = items["Exercise - Binary Search"]
    assert binary["kind"] == "deadline"
    assert binary["starts_at"] == binary["ends_at"] == datetime(2027, 1, 4, 23, 59, tzinfo=TZ)
    assert items["Campus holiday"]["kind"] == "all_day"

    source = CalendarSource(name="Canvas", provider="canvas", url="https://school.example/feed.ics")
    db.add(source)
    db.flush()
    feeds.store(db, source, list(items.values()), NOW)
    externals = db.scalars(select(ExternalEvent)).all()

    def listed(now):
        today = now.astimezone(TZ).date()
        items = _upcoming(db, [], [], [], today, TZ, now, externals)
        return [(i["title"], i["meta"]) for i in items]

    # Monday 08:00: today's items in due-time order, then later days (the holiday is listed too).
    at_eight = listed(NOW)
    assert at_eight[:2] == [
        ("Quiz 2", "Due 9:00 am · CS 341"),
        ("Exercise - Binary Search", "Due 11:59 pm · CS 341"),
    ]
    assert ("Campus holiday", "All day") in at_eight
    # 10:00: the quiz is past due but stays in today's list instead of disappearing.
    assert listed(NOW + timedelta(hours=2))[0] == ("Quiz 2", "Was due 9:00 am · CS 341")
    # Tuesday: yesterday's items are gone.
    assert "Quiz 2" not in dict(listed(NOW + timedelta(days=1)))


def test_an_empty_feed_never_wipes_imported_deadlines(db, monkeypatch):
    source = CalendarSource(name="Canvas", provider="canvas", url="https://school.example/feed.ics")
    db.add(source)
    db.flush()
    feeds.store(db, source, feeds.parse(FEED, NOW, TZ), NOW)
    before = len(db.scalars(select(ExternalEvent)).all())
    empty = "\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN", "END:VCALENDAR"])
    monkeypatch.setattr(feeds, "_download", lambda url: empty)
    result = feeds.sync(db, source)
    assert len(db.scalars(select(ExternalEvent)).all()) == before
    assert "empty" in result["last_error"]
    # The failed attempt is recorded, but the last good import keeps its own time.
    assert result["last_success_at"] == NOW
    assert result["last_synced_at"] != NOW


def test_items_due_on_the_last_evening_of_the_window_are_imported():
    # 5:30 pm Los Angeles on the window's last day is already the next day in UTC.
    last_day = NOW.astimezone(TZ).date() + timedelta(days=feeds.FUTURE_DAYS - 1)
    due = datetime.combine(last_day, datetime.min.time().replace(hour=17, minute=30), tzinfo=TZ)
    stamp = due.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    feed = FEED.replace(
        "END:VCALENDAR",
        "\n".join(
            [
                "BEGIN:VEVENT",
                "UID:event-assignment-999",
                "DTSTAMP:20270101T000000Z",
                "SUMMARY:Group project [CSS 360]",
                f"DTSTART:{stamp}",
                f"DTEND:{stamp}",
                "END:VEVENT",
                "END:VCALENDAR",
            ]
        ),
    )
    items = {i["title"]: i for i in feeds.parse(feed, NOW, TZ)}
    assert items["Group project"]["starts_at"] == due


def test_importing_an_ics_file_and_reimporting_replaces_it(client):
    from app.db import utcnow

    def ics(*titles):
        day = utcnow().date() + timedelta(days=3)
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Google Inc//Google Calendar//EN"]
        for i, title in enumerate(titles):
            lines += [
                "BEGIN:VEVENT",
                f"UID:evt-{i}",
                "DTSTAMP:20260101T000000Z",
                f"SUMMARY:{title}",
                f"DTSTART:{day:%Y%m%d}T180000Z",
                f"DTEND:{day:%Y%m%d}T190000Z",
                "END:VEVENT",
            ]
        return "\n".join([*lines, "END:VCALENDAR"])

    first = client.post(
        "/api/calendars/import",
        json={"filename": "Work shifts.ics", "content": ics("Shift", "Team dinner")},
    )
    assert first.status_code == 201
    body = first.json()
    assert (body["name"], body["events"], body["imported_file"]) == ("Work shifts", 2, True)
    assert body["url_hint"] == "Imported file · Work shifts.ics"
    titles = {s["title"] for s in client.get("/api/sessions").json() if s["external"]}
    assert {"Shift", "Team dinner"} <= titles

    again = client.post(
        "/api/calendars/import", json={"filename": "Work shifts.ics", "content": ics("Shift")}
    ).json()
    assert again["id"] == body["id"] and again["events"] == 1
    assert len(client.get("/api/calendars").json()) == 1
    assert client.post(f"/api/calendars/{body['id']}/sync").status_code == 409

    tomo = client.get("/api/export.ics").text
    refused = client.post(
        "/api/calendars/import", json={"filename": "tomo-schedule.ics", "content": tomo}
    )
    assert refused.status_code == 422 and "Tomo export" in refused.json()["detail"]
    empty = "\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//X//EN", "END:VCALENDAR"])
    assert (
        client.post(
            "/api/calendars/import", json={"filename": "e.ics", "content": empty}
        ).status_code
        == 422
    )


def test_imported_files_never_count_as_stale_feeds(db):
    db.add(CalendarSource(name="Shifts", provider="other", url="file:Shifts.ics"))
    db.flush()
    assert feeds.stale_sources(db, NOW) == []

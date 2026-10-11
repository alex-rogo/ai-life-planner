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

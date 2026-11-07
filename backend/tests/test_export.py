import icalendar


def test_export_has_events_trips_and_planned_work_and_imports_only_on_request(client):
    client.post(
        "/api/obligations",
        json={
            "title": "Programming 342",
            "weekdays": [0, 2],
            "start_time": "13:15",
            "end_time": "15:15",
            "travel_minutes": 30,
            "travel_mode": "Bus",
        },
    )
    client.post(
        "/api/tasks", json={"title": "LeetCode", "duration_minutes": 60, "recurrence": "daily"}
    )
    client.post("/api/calendars", json={"provider": "demo", "url": "demo://canvas"})

    response = client.get("/api/export.ics", params={"weeks": 2})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "tomo-schedule.ics" in response.headers["content-disposition"]
    events = icalendar.Calendar.from_ical(response.content).walk("VEVENT")
    titles = [str(e["SUMMARY"]) for e in events]
    assert titles.count("Programming 342") == 4  # Mon and Wed for two weeks
    assert titles.count("Bus to Programming 342") == 4 and titles.count("Bus home") == 4
    assert "LeetCode" in titles
    assert not any(t.startswith("Due:") for t in titles)
    assert len({str(e["UID"]) for e in events}) == len(events)

    with_imports = client.get("/api/export.ics", params={"weeks": 2, "imported": True}).content
    assert any(
        str(e["SUMMARY"]).startswith("Due:")
        for e in icalendar.Calendar.from_ical(with_imports).walk("VEVENT")
    )

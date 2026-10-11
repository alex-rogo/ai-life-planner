import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import TaskCreate
from app.services.ai.actions import ActionBatch, CreateTask


def test_action_schema_rejects_invalid_operations():
    with pytest.raises(ValidationError):
        ActionBatch.model_validate(
            {"actions": [{"kind": "execute_sql", "sql": "drop table tasks"}], "explanation": "bad"}
        )
    with pytest.raises(ValidationError):
        ActionBatch.model_validate(
            {
                "actions": [{"kind": "create_task", "task": {"title": "bad", "priority": 8}}],
                "explanation": "bad",
            }
        )


def propose_and_apply(client, message):
    response = client.post("/api/assistant", json={"message": message})
    assert response.status_code == 200, response.text
    proposal = response.json()["proposal"]
    applied = client.post(f"/api/proposals/{proposal['id']}/apply")
    assert applied.status_code == 200, applied.text
    return proposal, applied.json()


def test_demo_goal_and_conversational_rescheduling(client):
    response = client.post(
        "/api/assistant", json={"message": "I want to get good at C++ by December."}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "demo"
    assert body["defaults"]
    # A proposal is only a preview until applied.
    assert client.get("/api/goals").json() == []
    assert body["proposal"]["changes"][0]["kind"] == "New goal"
    assert any(s["change"] == "Added" for s in body["proposal"]["preview"]["sessions"])
    client.post(f"/api/proposals/{body['proposal']['id']}/apply")
    assert len(client.get("/api/goals").json()) == 1
    assert len(client.get("/api/tasks").json()) == 2
    propose_and_apply(client, "I want to work out four times per week.")
    proposal, applied = propose_and_apply(client, "Move my workout to tonight.")
    assert applied["reply"].startswith("Done.")
    messages = client.get("/api/messages").json()
    assert messages[-1]["proposal_id"] == proposal["id"]


def test_discard_keeps_plan_and_proposals_resolve_once(client):
    response = client.post(
        "/api/assistant", json={"message": "I need to study LeetCode for an hour every day."}
    )
    identifier = response.json()["proposal"]["id"]
    assert client.get("/api/proposals/current").json()["id"] == identifier
    assert client.post(f"/api/proposals/{identifier}/discard").status_code == 200
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/proposals/current").json() is None
    assert client.post(f"/api/proposals/{identifier}/apply").status_code == 409


def test_undo_restores_previous_plan_until_something_changes(client):
    proposal, _ = propose_and_apply(client, "I need to study LeetCode for an hour every day.")
    assert client.get("/api/proposals/current").json()["can_undo"]
    assert client.post(f"/api/proposals/{proposal['id']}/undo").status_code == 200
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/sessions").json() == []
    assert client.post(f"/api/proposals/{proposal['id']}/undo").status_code == 409

    proposal, _ = propose_and_apply(client, "I need to study LeetCode for an hour every day.")
    client.post("/api/tasks", json={"title": "Edited elsewhere"})
    assert client.get("/api/proposals/current").json() is None
    response = client.post(f"/api/proposals/{proposal['id']}/undo")
    assert response.status_code == 409
    assert "changed" in response.json()["detail"]


def test_unknown_demo_request_clarifies_without_mutation(client):
    response = client.post("/api/assistant", json={"message": "Schedule something"})
    assert response.json()["needs_clarification"]
    assert response.json()["proposal"] is None
    assert client.get("/api/tasks").json() == []


def test_batch_rolls_back_if_later_action_invalid(client, monkeypatch):
    batch = ActionBatch.model_validate(
        {
            "actions": [
                {"kind": "create_task", "task": {"title": "Should rollback"}},
                {"kind": "complete_task", "task_id": str(uuid4())},
            ],
            "explanation": "batch",
        }
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: batch)
    assert client.post("/api/assistant", json={"message": "batch"}).status_code == 404
    assert client.get("/api/tasks").json() == []


def test_gemini_structured_output_and_invalid_reply(monkeypatch):
    from app.services.ai.interpreter import interpret

    mock = MagicMock()
    client = mock.return_value.__enter__.return_value
    valid = ActionBatch(
        actions=[CreateTask(kind="create_task", task=TaskCreate(title="Read"))],
        explanation="Create reading task",
    )
    client.models.generate_content.return_value.text = valid.model_dump_json()
    monkeypatch.setattr("app.services.ai.interpreter.genai.Client", mock)
    config = Settings(ai_mode="gemini", gemini_api_key="fake-test-key")
    assert interpret(config, "read", {}).actions[0].task.title == "Read"
    call = client.models.generate_content.call_args
    assert call.kwargs["config"].response_json_schema
    client.models.generate_content.return_value.text = json.dumps({"unexpected": "bad"})
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        interpret(config, "read", {})
    assert error.value.status_code == 502


def test_missing_key_is_graceful():
    from fastapi import HTTPException

    from app.services.ai.interpreter import interpret

    with pytest.raises(HTTPException) as error:
        interpret(Settings(ai_mode="gemini", gemini_api_key=""), "read", {})
    assert error.value.status_code == 503


def test_provider_schema_uses_supported_union_representation():
    from app.services.ai.interpreter import provider_schema

    schema = provider_schema()
    assert "discriminator" not in json.dumps(schema)
    assert "oneOf" not in json.dumps(schema)
    assert schema["$defs"]["CreateGoal"]["properties"]["kind"]["enum"] == ["create_goal"]


def test_demo_exact_title_resolves_ambiguous_category():
    from app.services.ai.interpreter import demo_interpret

    first, second = str(uuid4()), str(uuid4())
    context = {
        "now": "2027-01-04T15:00:00+00:00",
        "preferences": {"timezone": "America/Los_Angeles"},
        "tasks": [
            {"id": first, "title": "C++ foundations", "status": "pending"},
            {"id": second, "title": "C++ project", "status": "pending"},
        ],
    }
    result = demo_interpret("I need to finish C++ foundations first.", context)
    assert str(result.actions[0].task_id) == first
    assert result.actions[0].priority == 5


def test_recurring_completion_credits_today_not_tomorrow(db):
    from datetime import timedelta

    from test_scheduler import NOW, add

    from app.models import ScheduleSession
    from app.services.ai.actions import CompleteTask
    from app.services.ai.pipeline import complete

    task = add(db, recurrence="daily")
    today = ScheduleSession(
        task_id=task.id,
        title=task.title,
        starts_at=NOW + timedelta(hours=1),
        ends_at=NOW + timedelta(hours=2),
    )
    tomorrow = ScheduleSession(
        task_id=task.id,
        title=task.title,
        starts_at=NOW + timedelta(days=1, hours=1),
        ends_at=NOW + timedelta(days=1, hours=2),
    )
    db.add_all([today, tomorrow])
    db.flush()
    complete(db, CompleteTask(kind="complete_task", task_id=task.id), NOW + timedelta(hours=3))
    assert today.status == "completed"
    assert tomorrow.status == "planned"
    assert task.completed_minutes == 60


def test_ai_cannot_enable_monitoring_as_a_side_effect(client, monkeypatch):
    from app.schemas import Preferences
    from app.services.ai.actions import SetPreference

    prefs = Preferences(**client.get("/api/preferences").json())
    prefs.monitoring_enabled = True
    batch = ActionBatch(
        actions=[SetPreference(kind="set_preference", preferences=prefs)],
        explanation="Change preferences",
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: batch)
    response = client.post("/api/assistant", json={"message": "Change my sleep hours"})
    assert response.status_code == 422
    assert not client.get("/api/preferences").json()["monitoring_enabled"]


def test_recreated_rows_at_the_same_time_are_not_reported_as_moves():
    from zoneinfo import ZoneInfo

    from app.services.ai.actions import Reschedule
    from app.services.ai.pipeline import describe

    def view(identifier, start, end):
        return {
            "id": identifier,
            "task_id": "t",
            "obligation_id": None,
            "title": "Workout",
            "status": "planned",
            "category": "routine",
            "starts_at": start,
            "ends_at": end,
        }

    batch = ActionBatch(actions=[Reschedule(kind="reschedule")], explanation="Replan")
    before = [view("a", "2027-01-04T19:00:00+00:00", "2027-01-04T20:00:00+00:00")]
    after = [
        view("b", "2027-01-04T19:00:00+00:00", "2027-01-04T20:00:00+00:00"),
        view("c", "2027-01-05T19:00:00+00:00", "2027-01-05T20:00:00+00:00"),
    ]
    changes = describe(before, after, batch, ZoneInfo("America/Los_Angeles"))
    assert [c["kind"] for c in changes] == ["Added"]
    assert [v["change"] for v in after] == [None, "Added"]


def test_apply_commits_exactly_the_preview_without_solving_again(client, monkeypatch):
    response = client.post(
        "/api/assistant", json={"message": "I need to study LeetCode for an hour every day."}
    )
    proposal = response.json()["proposal"]
    shown = {(s["title"], s["starts_at"], s["ends_at"]) for s in proposal["preview"]["sessions"]}

    def no_solving(*_):
        raise AssertionError("Applying an unchanged preview must not run the solver")

    monkeypatch.setattr("app.services.ai.pipeline.generate_plan", no_solving)
    assert client.post(f"/api/proposals/{proposal['id']}/apply").status_code == 200
    window = {"start": proposal["preview"]["start"], "end": proposal["preview"]["end"]}
    applied = client.get("/api/sessions", params=window).json()
    assert {(s["title"], s["starts_at"], s["ends_at"]) for s in applied} == shown
    assert client.get("/api/proposals/current").json()["can_undo"]


def test_apply_plans_again_when_something_changed_since_the_preview(client):
    response = client.post(
        "/api/assistant", json={"message": "I need to study LeetCode for an hour every day."}
    )
    identifier = response.json()["proposal"]["id"]
    client.post("/api/tasks", json={"title": "Added after the preview"})
    assert client.post(f"/api/proposals/{identifier}/apply").status_code == 200
    titles = {t["title"] for t in client.get("/api/tasks").json()}
    assert titles == {"LeetCode practice", "Added after the preview"}

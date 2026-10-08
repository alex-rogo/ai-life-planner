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


def test_demo_goal_and_conversational_rescheduling(client):
    response = client.post(
        "/api/assistant", json={"message": "I want to get good at C++ by December."}
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "demo"
    assert len(client.get("/api/goals").json()) == 1
    assert len(client.get("/api/tasks").json()) == 2
    assert response.json()["defaults"]
    client.post("/api/assistant", json={"message": "I want to work out four times per week."})
    response = client.post("/api/assistant", json={"message": "Move my workout to tonight."})
    assert response.status_code == 200
    assert not response.json()["needs_clarification"]
    assert client.get("/api/messages").json()


def test_unknown_demo_request_clarifies_without_mutation(client):
    response = client.post("/api/assistant", json={"message": "Schedule something"})
    assert response.json()["needs_clarification"]
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

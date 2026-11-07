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


def test_deepseek_json_mode_and_errors(monkeypatch):
    from fastapi import HTTPException

    from app.services.ai.interpreter import interpret

    valid = ActionBatch(
        actions=[CreateTask(kind="create_task", task=TaskCreate(title="Read"))],
        explanation="Create reading task",
    )
    reply = MagicMock()
    reply.json.return_value = {"choices": [{"message": {"content": valid.model_dump_json()}}]}
    post = MagicMock(return_value=reply)
    monkeypatch.setattr("app.services.ai.interpreter.httpx.post", post)
    config = Settings(ai_mode="deepseek", deepseek_api_key="fake-test-key")
    assert interpret(config, "read", {}).actions[0].task.title == "Read"
    request = post.call_args
    assert request.args[0] == "https://api.deepseek.com/chat/completions"
    assert request.kwargs["json"]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in request.kwargs["json"]["messages"][0]["content"]

    reply.json.return_value = {"choices": [{"message": {"content": '{"unexpected": "bad"}'}}]}
    with pytest.raises(HTTPException) as error:
        interpret(config, "read", {})
    assert error.value.status_code == 502
    post.side_effect = RuntimeError("network down, key fake-test-key")
    with pytest.raises(HTTPException) as error:
        interpret(config, "read", {})
    assert error.value.status_code == 503 and "fake-test-key" not in error.value.detail
    with pytest.raises(HTTPException) as error:
        interpret(Settings(ai_mode="deepseek", deepseek_api_key=""), "read", {})
    assert error.value.status_code == 503 and "DEEPSEEK_API_KEY" in error.value.detail


def test_one_off_events_take_their_weekday_from_the_date():
    from datetime import date

    from app.schemas import ObligationCreate

    tuesday = date(2026, 10, 20)
    event = ObligationCreate(
        title="Dentist",
        weekdays=[2],
        start_time="15:00",
        end_time="16:00",
        start_date=tuesday,
        end_date=tuesday,
    )
    assert event.weekdays == [1]


def test_an_invalid_reply_gets_one_repair_attempt(monkeypatch):
    from app.services.ai.interpreter import interpret

    valid = ActionBatch(
        actions=[CreateTask(kind="create_task", task=TaskCreate(title="Read"))],
        explanation="Create reading task",
    )
    replies = iter(
        ['{"actions": [{"kind": "create_task"}], "explanation": "x"}', valid.model_dump_json()]
    )
    sent = []

    def fake(settings, system, payload, kind, fast=False):
        sent.append(json.loads(payload))
        return next(replies)

    monkeypatch.setattr("app.services.ai.interpreter._deepseek", fake)
    config = Settings(ai_mode="deepseek", deepseek_api_key="fake-test-key")
    assert interpret(config, "read", {}).actions[0].task.title == "Read"
    assert "your_previous_reply_was_invalid" not in sent[0]
    repair = sent[1]["your_previous_reply_was_invalid"]
    assert repair["problems"] and "create_task" in repair["reply"]


def test_follow_ups_see_the_pending_proposal(client, db, monkeypatch):
    from app.services.ai.pipeline import context_for

    first = ActionBatch(
        actions=[CreateTask(kind="create_task", task=TaskCreate(title="Essay"))],
        explanation="Add essay",
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: first)
    assert client.post("/api/assistant", json={"message": "essay"}).status_code == 200
    from app.db import utcnow

    context = context_for(db, utcnow())
    assert context["pending_proposal"]["request"] == "essay"
    assert context["pending_proposal"]["actions"][0]["task"]["title"] == "Essay"


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


def test_deepseek_prompt_schema_keeps_fields_and_drops_display_metadata():
    from app.services.ai.interpreter import prompt_schema

    schema = prompt_schema(ActionBatch)
    task = schema["$defs"]["TaskCreate"]
    assert "title" in task["properties"]
    assert "description" in task["properties"]
    assert "title" not in task
    assert "description" not in task["properties"]["title"]
    assert len(json.dumps(schema)) < len(json.dumps(ActionBatch.model_json_schema()))


def test_provider_context_keeps_planning_fields_without_bulk_metadata():
    from app.services.ai.interpreter import compact_context

    context = {
        "preferences": {"timezone": "America/Los_Angeles"},
        "tasks": [
            {
                "id": "task-1",
                "title": "Workout",
                "status": "pending",
                "description": "Evening exercise",
                "days": [0, 2, 4],
                "window_start": "17:00",
                "window_end": "21:00",
                "created_at": "2026-01-01",
                "activity_apps": ["app.exe"],
            }
        ],
        "goals": [{"id": "goal-1", "title": "Fitness", "description": "x" * 4000}],
        "events": [],
        "recent_messages": [{"role": "user", "content": "x" * 1000}],
    }
    compact = compact_context(context, "Move my workout")
    assert compact["tasks"][0]["days"] == [0, 2, 4]
    assert compact["tasks"][0]["description"] == "Evening exercise"
    assert "created_at" not in compact["tasks"][0]
    assert "activity_apps" not in compact["tasks"][0]
    assert "description" not in compact["goals"][0]
    assert len(compact["recent_messages"][0]["content"]) == 800


def test_fast_single_call_is_default(monkeypatch):
    from app.services.ai.interpreter import _deepseek, review

    settings = Settings(ai_mode="deepseek", deepseek_api_key="fake-test-key")
    assert settings.deepseek_planner_model == ""
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(*args, **kwargs):
        sent.append(kwargs["json"])
        return Response()

    monkeypatch.setattr("app.services.ai.interpreter.httpx.post", fake_post)
    _deepseek(settings, "system", "{}", ActionBatch)
    assert sent[0]["model"] == "deepseek-chat"
    assert (
        review(
            settings,
            "move workout",
            {},
            ActionBatch(actions=[CreateTask(kind="create_task", task=TaskCreate(title="Workout"))]),
            "",
            [],
        )
        is None
    )


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


def test_a_reply_answers_without_proposing_and_keeps_the_pending_proposal(client, monkeypatch):
    from app.services.ai.actions import Reply

    first = ActionBatch(
        actions=[CreateTask(kind="create_task", task=TaskCreate(title="Essay"))],
        explanation="Add essay",
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: first)
    pending = client.post("/api/assistant", json={"message": "essay"}).json()["proposal"]
    advice = ActionBatch(
        actions=[Reply(kind="reply", message="Five 45-minute sessions a week works well.")],
        explanation="Advice",
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: advice)
    answer = client.post("/api/assistant", json={"message": "how often should I practice?"}).json()
    assert answer["proposal"] is None
    assert answer["reply"] == "Five 45-minute sessions a week works well."
    current = client.get("/api/proposals/current").json()
    assert current["id"] == pending["id"] and current["status"] == "pending"
    assert client.get("/api/messages").json()[-1]["content"].startswith("Five 45-minute")


def test_the_review_can_revise_a_proposal_before_the_user_sees_it(client, monkeypatch):
    from app.services.ai.interpreter import Review

    first = ActionBatch(
        actions=[
            CreateTask(kind="create_task", task=TaskCreate(title="LeetCode", category="focus"))
        ],
        explanation="Add LeetCode",
    )
    better = ActionBatch(
        actions=[
            CreateTask(
                kind="create_task",
                task=TaskCreate(title="LeetCode", window_start="10:00", window_end="22:00"),
            )
        ],
        explanation="Add LeetCode after 10",
    )
    seen = {}

    def fake_review(settings, message, context, batch, week, missing):
        seen["week"] = week
        return Review(
            verdict="revise",
            summary="LeetCode stays after 10 am.",
            concerns=["Mornings are busy."],
            revised=better,
        )

    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: first)
    monkeypatch.setattr("app.services.ai.pipeline.review", fake_review)
    proposal = client.post("/api/assistant", json={"message": "leetcode"}).json()["proposal"]
    assert "LeetCode" in seen["week"] and "NEW" in seen["week"]
    assert proposal["title"] == "LeetCode stays after 10 am"
    assert "Heads up: Mornings are busy." in proposal["footer"]
    client.post(f"/api/proposals/{proposal['id']}/apply")
    task = client.get("/api/tasks").json()[0]
    assert (task["window_start"], task["window_end"]) == ("10:00", "22:00")


def test_the_assistant_can_edit_and_delete_events(client, monkeypatch):
    from app.schemas import ObligationCreate
    from app.services.ai.actions import DeleteObligation, UpdateObligation

    event = client.post(
        "/api/obligations",
        json={"title": "Class", "weekdays": [0], "start_time": "13:00", "end_time": "15:00"},
    ).json()
    moved = ObligationCreate(title="Class", weekdays=[2], start_time="13:00", end_time="15:00")
    for batch in (
        ActionBatch(
            actions=[
                UpdateObligation(
                    kind="update_obligation", obligation_id=event["id"], obligation=moved
                )
            ],
            explanation="Move class",
        ),
        ActionBatch(
            actions=[DeleteObligation(kind="delete_obligation", obligation_id=event["id"])],
            explanation="Drop class",
        ),
    ):
        monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_, b=batch: b)
        proposal = client.post("/api/assistant", json={"message": "change"}).json()["proposal"]
        client.post(f"/api/proposals/{proposal['id']}/apply")
        if batch.actions[0].kind == "update_obligation":
            assert client.get("/api/obligations").json()[0]["weekdays"] == [2]
    assert client.get("/api/obligations").json() == []


def test_changes_are_described_per_task_not_per_session():
    from zoneinfo import ZoneInfo

    from app.services.ai.pipeline import describe

    tz = ZoneInfo("America/Los_Angeles")

    def view(i, day, hour):
        start = f"2026-10-{day:02d}T{hour + 7:02d}:00:00+00:00"
        end = f"2026-10-{day:02d}T{hour + 8:02d}:00:00+00:00"
        return {
            "id": i,
            "task_id": "w",
            "obligation_id": None,
            "title": "Workout",
            "status": "planned",
            "starts_at": start,
            "ends_at": end,
            "category": "routine",
        }

    before = [view("a", 12, 9), view("b", 14, 9)]
    after = [view("c", 16, 9), view("d", 17, 9), view("e", 18, 9)]
    batch = ActionBatch(actions=[CreateTask(kind="create_task", task=TaskCreate(title="x"))])
    changes = describe(before, after, batch, tz)
    assert changes[0] == {
        "kind": "Moved",
        "title": "Workout",
        "detail": "Fri, Sat, Sun 9:00 am–10:00 am (was Mon, Wed 9:00 am–10:00 am)",
    }


def test_a_rerun_edit_only_changes_what_the_assistant_set(client, monkeypatch):
    from app.schemas import TaskPatch
    from app.services.ai.actions import UpdateTask

    task = client.post(
        "/api/tasks",
        json={
            "title": "Workout",
            "duration_minutes": 60,
            "window_start": "16:00",
            "window_end": "17:00",
        },
    ).json()
    edit = ActionBatch(
        actions=[
            UpdateTask(
                kind="update_task",
                task_id=task["id"],
                changes=TaskPatch(duration_minutes=45, min_session_minutes=45),
            )
        ]
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: edit)
    proposal = client.post("/api/assistant", json={"message": "shorter"}).json()["proposal"]
    # Something changes before Apply, so the stored batch is re-run instead of restored.
    client.post(
        "/api/obligations",
        json={"title": "Dentist", "weekdays": [0], "start_time": "08:00", "end_time": "09:00"},
    )
    assert client.post(f"/api/proposals/{proposal['id']}/apply").status_code == 200
    after = client.get("/api/tasks").json()[0]
    assert after["duration_minutes"] == 45
    assert (after["title"], after["window_start"], after["window_end"]) == (
        "Workout",
        "16:00",
        "17:00",
    )


def test_reply_options_are_kept_with_the_message(client, monkeypatch):
    from app.services.ai.actions import Reply

    ask = ActionBatch(
        actions=[
            Reply(
                kind="reply",
                message="Which four days?",
                options=["Mon-Thu at 4 pm", "Fri-Mon at 4 pm"],
            )
        ]
    )
    monkeypatch.setattr("app.services.ai.pipeline.interpret", lambda *_: ask)
    client.post("/api/assistant", json={"message": "four in a row"})
    last = client.get("/api/messages").json()[-1]
    assert last["content"] == "Which four days?"
    assert last["options"] == ["Mon-Thu at 4 pm", "Fri-Mon at 4 pm"]

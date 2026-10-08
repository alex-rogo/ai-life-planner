import secrets
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ChatMessage, Goal, Obligation, ScheduleSession, Suggestion, Task
from app.schemas import (
    ActivityBatch,
    ChatIn,
    GoalCreate,
    GoalOut,
    MessageOut,
    ObligationCreate,
    ObligationOut,
    PlanRequest,
    PlanResult,
    Preferences,
    SessionOut,
    SessionPatch,
    SuggestionDecision,
    SuggestionOut,
    TaskCreate,
    TaskOut,
    TaskPatch,
)
from app.services import activity, resources
from app.services.ai.interpreter import DEMO_COMMANDS
from app.services.ai.pipeline import execute_chat
from app.services.scheduler import generate_plan

app = FastAPI(
    title="AI Life Assistant",
    version="0.1.0",
    description="Local-first scheduling. Gemini interprets; CP-SAT plans.",
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Agent-Token"],
)
DB = Annotated[Session, Depends(get_db, scope="function")]


@app.exception_handler(ValidationError)
async def service_validation_error(_, exc):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
            ]
        },
    )


@app.exception_handler(OperationalError)
async def unavailable_database(_, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database unavailable. Check DATABASE_URL and migrations."},
    )


@app.get("/health", tags=["system"])
def health(db: DB):
    resources.preferences(db)
    return {"status": "ok"}


@app.get("/api/goals", response_model=list[GoalOut], tags=["goals"])
def goals(db: DB):
    return db.scalars(select(Goal).order_by(Goal.created_at)).all()


@app.post("/api/goals", response_model=GoalOut, status_code=201, tags=["goals"])
def add_goal(data: GoalCreate, db: DB):
    resources.preferences(db, lock=True)
    return resources.create_goal(db, data)


@app.put("/api/goals/{identifier}", response_model=GoalOut, tags=["goals"])
def edit_goal(identifier: UUID, data: GoalCreate, db: DB):
    resources.preferences(db, lock=True)
    row = resources.require(db, Goal, identifier)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    db.flush()
    return row


@app.delete("/api/goals/{identifier}", status_code=204, tags=["goals"])
def delete_goal(identifier: UUID, db: DB):
    resources.preferences(db, lock=True)
    db.delete(resources.require(db, Goal, identifier))
    return Response(status_code=204)


@app.get("/api/tasks", response_model=list[TaskOut], tags=["tasks"])
def tasks(db: DB):
    return db.scalars(select(Task).order_by(Task.priority.desc(), Task.created_at)).all()


@app.post("/api/tasks", response_model=TaskOut, status_code=201, tags=["tasks"])
def add_task(data: TaskCreate, db: DB):
    resources.preferences(db, lock=True)
    return resources.create_task(db, data)


@app.patch("/api/tasks/{identifier}", response_model=TaskOut, tags=["tasks"])
def edit_task(identifier: UUID, data: TaskPatch, db: DB):
    resources.preferences(db, lock=True)
    return resources.update_task(db, identifier, data)


@app.delete("/api/tasks/{identifier}", status_code=204, tags=["tasks"])
def delete_task(identifier: UUID, db: DB):
    resources.preferences(db, lock=True)
    db.delete(resources.require(db, Task, identifier))
    return Response(status_code=204)


@app.get("/api/preferences", response_model=Preferences, tags=["preferences"])
def get_preferences(db: DB):
    return resources.preferences(db)


@app.put("/api/preferences", response_model=Preferences, tags=["preferences"])
def put_preferences(data: Preferences, db: DB):
    return resources.save_preferences(db, data)


@app.get("/api/obligations", response_model=list[ObligationOut], tags=["obligations"])
def obligations(db: DB):
    return db.scalars(select(Obligation)).all()


@app.post("/api/obligations", response_model=ObligationOut, status_code=201, tags=["obligations"])
def add_obligation(data: ObligationCreate, db: DB):
    resources.preferences(db, lock=True)
    return resources.save_obligation(db, data)


@app.put("/api/obligations/{identifier}", response_model=ObligationOut, tags=["obligations"])
def edit_obligation(identifier: UUID, data: ObligationCreate, db: DB):
    resources.preferences(db, lock=True)
    return resources.save_obligation(db, data, identifier)


@app.delete("/api/obligations/{identifier}", status_code=204, tags=["obligations"])
def delete_obligation(identifier: UUID, db: DB):
    resources.preferences(db, lock=True)
    db.delete(resources.require(db, Obligation, identifier))
    return Response(status_code=204)


@app.get("/api/sessions", response_model=list[SessionOut], tags=["schedule"])
def sessions(db: DB, start: datetime | None = None, end: datetime | None = None):
    statement = select(ScheduleSession).order_by(ScheduleSession.starts_at)
    if start:
        if start.tzinfo is None:
            raise RequestValidationError(
                [{"loc": ["query", "start"], "msg": "Timezone required", "type": "value_error"}]
            )
        statement = statement.where(ScheduleSession.ends_at > start)
    if end:
        if end.tzinfo is None:
            raise RequestValidationError(
                [{"loc": ["query", "end"], "msg": "Timezone required", "type": "value_error"}]
            )
        statement = statement.where(ScheduleSession.starts_at < end)
    return db.scalars(statement.limit(2000)).all()


@app.patch("/api/sessions/{identifier}", response_model=SessionOut, tags=["schedule"])
def edit_session(identifier: UUID, data: SessionPatch, db: DB):
    resources.preferences(db, lock=True)
    return resources.update_session(db, identifier, data)


@app.post("/api/schedule/plan", response_model=PlanResult, tags=["schedule"])
def plan_schedule(data: PlanRequest, db: DB):
    return generate_plan(db, data)


@app.post("/api/assistant", tags=["assistant"])
def assistant(data: ChatIn, db: DB):
    return execute_chat(db, data, settings)


@app.get("/api/messages", response_model=list[MessageOut], tags=["assistant"])
def messages(db: DB):
    return list(
        reversed(
            db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(100)).all()
        )
    )


@app.get("/api/system", tags=["system"])
def system_status(db: DB):
    prefs = resources.preferences(db)
    return {
        "ai_mode": settings.ai_mode,
        "gemini_configured": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "demo_commands": DEMO_COMMANDS,
        "monitoring_enabled": prefs.monitoring_enabled,
        "agent_token_configured": bool(settings.agent_token),
        **activity.connection_status(db),
    }


@app.post("/api/activity", tags=["activity"])
def ingest_activity(
    data: ActivityBatch, db: DB, x_agent_token: Annotated[str | None, Header()] = None
):
    if (
        not settings.agent_token
        or not x_agent_token
        or not secrets.compare_digest(settings.agent_token, x_agent_token)
    ):
        raise HTTPException(401, "A configured X-Agent-Token is required")
    return activity.ingest(db, data)


@app.get("/api/suggestions", response_model=list[SuggestionOut], tags=["activity"])
def suggestions(db: DB):
    return db.scalars(
        select(Suggestion).where(Suggestion.status == "pending").order_by(Suggestion.created_at)
    ).all()


@app.post("/api/suggestions/{identifier}/decision", tags=["activity"])
def decide_suggestion(identifier: UUID, data: SuggestionDecision, db: DB):
    return activity.decide(db, identifier, data)

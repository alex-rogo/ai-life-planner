import secrets
from datetime import date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import clock_offset, get_db, utcnow
from app.models import (
    CalendarSource,
    ChatMessage,
    Goal,
    Obligation,
    ScheduleSession,
    Suggestion,
    Task,
)
from app.schemas import (
    ActivityBatch,
    CalendarFile,
    CalendarIn,
    CalendarOut,
    ChatIn,
    ChatOut,
    DecisionOut,
    GoalCreate,
    GoalOut,
    ItemCheck,
    MessageOut,
    ObligationCreate,
    ObligationOut,
    Overview,
    PlanRequest,
    PlanResult,
    Preferences,
    ProposalOut,
    SessionPatch,
    SessionView,
    SuggestionDecision,
    SuggestionOut,
    TaskCreate,
    TaskOut,
    TaskPatch,
)
from app.services import activity, checklist, demo, export, feeds, overview, resources, upkeep
from app.services.ai import pipeline
from app.services.ai.interpreter import DEMO_COMMANDS
from app.services.scheduler import generate_plan

app = FastAPI(
    title="AI Planner",
    version="0.1.0",
    description="Local-first scheduling. Gemini interprets; CP-SAT plans. Changes to tasks, "
    "obligations and preferences replan the week automatically.",
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
    row = resources.create_task(db, data)
    upkeep.replan(db)
    return row


@app.patch("/api/tasks/{identifier}", response_model=TaskOut, tags=["tasks"])
def edit_task(identifier: UUID, data: TaskPatch, db: DB):
    resources.preferences(db, lock=True)
    row = resources.update_task(db, identifier, data)
    upkeep.replan(db)
    return row


@app.delete("/api/tasks/{identifier}", status_code=204, tags=["tasks"])
def delete_task(identifier: UUID, db: DB):
    resources.preferences(db, lock=True)
    db.delete(resources.require(db, Task, identifier))
    db.flush()
    upkeep.replan(db)
    return Response(status_code=204)


@app.get("/api/preferences", response_model=Preferences, tags=["preferences"])
def get_preferences(db: DB):
    return resources.preferences(db)


@app.put("/api/preferences", response_model=Preferences, tags=["preferences"])
def put_preferences(data: Preferences, db: DB):
    moved = resources.preferences(db).timezone != data.timezone
    row = resources.save_preferences(db, data)
    if moved:
        # Date-only and floating feed times depend on the timezone: re-import on the next read.
        for source in db.scalars(select(CalendarSource)):
            source.last_synced_at = None
    upkeep.replan(db)
    return row


@app.get("/api/obligations", response_model=list[ObligationOut], tags=["obligations"])
def obligations(db: DB):
    return db.scalars(select(Obligation)).all()


@app.post("/api/obligations", response_model=ObligationOut, status_code=201, tags=["obligations"])
def add_obligation(data: ObligationCreate, db: DB):
    resources.preferences(db, lock=True)
    row = resources.save_obligation(db, data)
    upkeep.replan(db)
    return row


@app.put("/api/obligations/{identifier}", response_model=ObligationOut, tags=["obligations"])
def edit_obligation(identifier: UUID, data: ObligationCreate, db: DB):
    resources.preferences(db, lock=True)
    row = resources.save_obligation(db, data, identifier)
    upkeep.replan(db)
    return row


@app.delete("/api/obligations/{identifier}", status_code=204, tags=["obligations"])
def delete_obligation(identifier: UUID, db: DB):
    resources.preferences(db, lock=True)
    db.delete(resources.require(db, Obligation, identifier))
    db.flush()
    upkeep.replan(db)
    return Response(status_code=204)


@app.get("/api/sessions", response_model=list[SessionView], tags=["schedule"])
def sessions(db: DB, start: datetime | None = None, end: datetime | None = None):
    upkeep.settle(db)
    upkeep.ensure_plan(db)
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
    rows = upkeep.session_views(db, db.scalars(statement.limit(2000)).all())
    return rows + upkeep.external_views(db, start, end)


@app.patch("/api/sessions/{identifier}", response_model=SessionView, tags=["schedule"])
def edit_session(identifier: UUID, data: SessionPatch, db: DB):
    resources.preferences(db, lock=True)
    row = resources.update_session(db, identifier, data)
    if data.status in ("skipped", "missed"):
        upkeep.replan(db)
    return upkeep.session_views(db, [row])[0]


@app.put("/api/checklist/{item}", status_code=204, tags=["schedule"])
def check_item(item: str, data: ItemCheck, db: DB):
    """Check an item in the sidebar's task list off, or back on."""
    resources.preferences(db, lock=True)
    checklist.set_done(db, item, data.done)
    return Response(status_code=204)


@app.get("/api/export.ics", tags=["schedule"])
def export_calendar(
    db: DB,
    weeks: Annotated[int, Query(ge=1, le=26)] = 8,
    imported: bool = False,
):
    """Download the plan as an .ics file to import into another calendar app."""
    return Response(
        export.build(db, weeks, imported),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tomo-schedule.ics"'},
    )


@app.post("/api/schedule/plan", response_model=PlanResult, tags=["schedule"])
def plan_schedule(data: PlanRequest, db: DB):
    return generate_plan(db, data)


@app.get("/api/overview", response_model=Overview, tags=["schedule"])
def get_overview(
    db: DB,
    start: date | None = None,
    days: Annotated[int, Query(ge=1, le=42)] = 1,
):
    """Sidebar, stats and briefs for the visible range. Syncs stale calendar feeds and settles
    elapsed work first."""
    feeds.sync_stale(db)
    upkeep.settle(db)
    upkeep.ensure_plan(db)
    if start is None:
        start = utcnow().astimezone(ZoneInfo(resources.preferences(db).timezone)).date()
    return overview.build(db, start, days, settings)


@app.post("/api/assistant", response_model=ChatOut, tags=["assistant"])
def assistant(data: ChatIn, db: DB):
    """Interpret a request and preview its effect. Apply the returned proposal to commit it."""
    return pipeline.propose(db, data, settings)


@app.get("/api/proposals/current", response_model=ProposalOut | None, tags=["assistant"])
def current_proposal(db: DB):
    return pipeline.current_proposal(db)


@app.post("/api/proposals/{identifier}/apply", response_model=DecisionOut, tags=["assistant"])
def apply_proposal(identifier: UUID, db: DB):
    return pipeline.apply_proposal(db, identifier, settings)


@app.post("/api/proposals/{identifier}/discard", response_model=DecisionOut, tags=["assistant"])
def discard_proposal(identifier: UUID, db: DB):
    return pipeline.discard_proposal(db, identifier, settings)


@app.post("/api/proposals/{identifier}/undo", response_model=DecisionOut, tags=["assistant"])
def undo_proposal(identifier: UUID, db: DB):
    return pipeline.undo_proposal(db, identifier, settings)


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
        "now": utcnow(),
        "demo_clock": bool(clock_offset()),
        "ai_mode": settings.ai_mode,
        "gemini_configured": bool(
            settings.deepseek_api_key if settings.ai_mode == "deepseek" else settings.gemini_api_key
        ),
        "gemini_model": settings.deepseek_model
        if settings.ai_mode == "deepseek"
        else settings.gemini_model,
        "demo_commands": DEMO_COMMANDS,
        "sample_data_tools": demo.allowed(settings),
        "calendars": [
            {
                "name": c.name,
                "provider": c.provider,
                "last_synced_at": c.last_synced_at,
                "last_success_at": c.last_success_at,
                "error": c.last_error,
            }
            for c in db.scalars(select(CalendarSource).order_by(CalendarSource.created_at))
        ],
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


@app.get("/api/calendars", response_model=list[CalendarOut], tags=["calendars"])
def calendars(db: DB):
    rows = db.scalars(select(CalendarSource).order_by(CalendarSource.created_at)).all()
    return [feeds.out(db, row) for row in rows]


@app.post("/api/calendars", response_model=CalendarOut, status_code=201, tags=["calendars"])
def connect_calendar(data: CalendarIn, db: DB):
    """Subscribe to an .ics feed. Its events import as fixed, read-only blocks and deadlines."""
    return feeds.connect(db, data.provider, data.name, data.url)


@app.post("/api/calendars/import", response_model=CalendarOut, status_code=201, tags=["calendars"])
def import_calendar(data: CalendarFile, db: DB):
    """Import an .ics file once: fixed, read-only events and deadlines, like a feed that never syncs."""
    return feeds.import_file(db, data.filename, data.content)


@app.post("/api/calendars/{identifier}/sync", response_model=CalendarOut, tags=["calendars"])
def sync_calendar(identifier: UUID, db: DB):
    return feeds.sync(db, feeds.require_source(db, identifier))


@app.delete("/api/calendars/{identifier}", status_code=204, tags=["calendars"])
def disconnect_calendar(identifier: UUID, db: DB):
    feeds.disconnect(db, feeds.require_source(db, identifier))
    return Response(status_code=204)


@app.post("/api/demo/clear", status_code=204, tags=["demo"])
def clear_demo(db: DB):
    """Demo mode only: empty the planner (settings are kept)."""
    demo.clear(db, settings)
    return Response(status_code=204)


@app.post("/api/demo/populate", status_code=204, tags=["demo"])
def populate_demo(db: DB):
    """Demo mode only: replace everything with the sample week and the demo Canvas feed."""
    demo.populate(db, settings)
    return Response(status_code=204)

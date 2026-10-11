from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import ChatMessage, Goal, Proposal, ScheduleSession, Task
from app.schemas import (
    ChatIn,
    GoalOut,
    PlanRequest,
    PlanResult,
    Preferences,
    ProposalOut,
    SessionPatch,
    TaskOut,
    TaskPatch,
)
from app.services import resources
from app.services.ai.actions import (
    ActionBatch,
    Clarify,
    CompleteTask,
    CreateGoal,
    CreateObligation,
    CreateTask,
    Reschedule,
    SetPreference,
    UpdateTask,
)
from app.services.ai.interpreter import interpret
from app.services.history import fingerprint, restore, snapshot
from app.services.scheduler import generate_plan, local_midnight
from app.services.upkeep import session_views, sessions_between


def context_for(db: Session, now: datetime) -> dict:
    return {
        "now": now.isoformat(),
        "preferences": Preferences.model_validate(resources.preferences(db)).model_dump(
            mode="json"
        ),
        "tasks": [
            TaskOut.model_validate(t).model_dump(mode="json")
            for t in db.scalars(select(Task).order_by(Task.created_at).limit(200))
        ],
        "goals": [
            GoalOut.model_validate(g).model_dump(mode="json")
            for g in db.scalars(select(Goal).order_by(Goal.created_at).limit(100))
        ],
        "recent_messages": [
            {"role": m.role, "content": m.content}
            for m in reversed(
                db.scalars(
                    select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(6)
                ).all()
            )
        ],
    }


def postpone(db: Session, action: Reschedule, now: datetime):
    tasks = (
        [resources.require(db, Task, action.task_id)]
        if action.task_id
        else db.scalars(select(Task).where(Task.status == "pending")).all()
    )
    for task in tasks:
        if task.status != "pending":
            raise HTTPException(409, "Only pending tasks can be rescheduled")
        changes = {}
        if action.delay_minutes or action.tonight:
            not_before = now + timedelta(minutes=action.delay_minutes)
            if action.tonight:
                tz = ZoneInfo(resources.preferences(db).timezone)
                evening = datetime.combine(
                    now.astimezone(tz).date(), time(18), tzinfo=tz
                ).astimezone(UTC)
                not_before = max(not_before, evening)
            changes["not_before"] = not_before
            active = db.scalars(
                select(ScheduleSession).where(
                    ScheduleSession.task_id == task.id,
                    ScheduleSession.status == "planned",
                    ScheduleSession.starts_at <= now,
                    ScheduleSession.ends_at > now,
                )
            ).all()
            for session in active:
                if session.locked:
                    raise HTTPException(409, "Unlock the active session before postponing it")
                resources.update_session(db, session.id, SessionPatch(status="skipped"))
        if action.priority is not None:
            changes["priority"] = action.priority
        if changes:
            resources.update_task(db, task.id, TaskPatch(**changes))


def complete(db: Session, action: CompleteTask, now: datetime):
    task = resources.require(db, Task, action.task_id)
    session = db.scalar(
        select(ScheduleSession)
        .where(
            ScheduleSession.task_id == task.id,
            ScheduleSession.status == "planned",
            ScheduleSession.starts_at <= now,
            ScheduleSession.ends_at > now,
        )
        .order_by(ScheduleSession.starts_at)
    )
    if not session and task.recurrence != "none":
        tz = ZoneInfo(resources.preferences(db).timezone)
        today = now.astimezone(tz).date()
        session = db.scalar(
            select(ScheduleSession)
            .where(
                ScheduleSession.task_id == task.id,
                ScheduleSession.status == "planned",
                ScheduleSession.starts_at >= local_midnight(today, tz),
                ScheduleSession.starts_at < local_midnight(today + timedelta(days=1), tz),
            )
            .order_by(ScheduleSession.starts_at.desc())
        )
    if session:
        resources.update_session(
            db, session.id, SessionPatch(status="completed", actual_minutes=action.actual_minutes)
        )
    elif task.recurrence == "none":
        resources.update_task(db, task.id, TaskPatch(status="completed"))
    else:
        raise HTTPException(409, "Generate a session for today before completing recurring work")


def apply_batch(db: Session, batch: ActionBatch, request: PlanRequest, now: datetime):
    """Apply validated actions, then replan. Callers own the transaction."""
    resources.preferences(db, lock=True)
    for action in batch.actions:
        if isinstance(action, CreateGoal):
            goal = resources.create_goal(db, action.goal)
            for task in action.tasks:
                if task.goal_id:
                    raise HTTPException(422, "New goal tasks cannot refer to a different goal")
                resources.create_task(db, task.model_copy(update={"goal_id": goal.id}))
        elif isinstance(action, CreateTask):
            resources.create_task(db, action.task)
        elif isinstance(action, UpdateTask):
            resources.update_task(db, action.task_id, action.changes)
        elif isinstance(action, CreateObligation):
            resources.save_obligation(db, action.obligation)
        elif isinstance(action, SetPreference):
            if (
                action.preferences.monitoring_enabled
                != resources.preferences(db).monitoring_enabled
            ):
                raise HTTPException(
                    422,
                    "Change activity monitoring explicitly in Settings; assistant preferences only change scheduling.",
                )
            resources.save_preferences(db, action.preferences)
        elif isinstance(action, Reschedule):
            postpone(db, action, now)
        elif isinstance(action, CompleteTask):
            complete(db, action, now)
    return generate_plan(db, request, now)


def _window(request: PlanRequest, now: datetime, tz: ZoneInfo):
    first = request.start_date or now.astimezone(tz).date()
    return local_midnight(first, tz), local_midnight(first + timedelta(days=request.days), tz)


def _views(db: Session, start: datetime, end: datetime) -> list[dict]:
    rows = [s for s in sessions_between(db, start, end) if s.status in ("planned", "completed")]
    return session_views(db, rows)


def _when(stamp: str, tz: ZoneInfo, with_day=True) -> str:
    local = datetime.fromisoformat(stamp).astimezone(tz)
    clock = local.strftime("%I:%M %p").lstrip("0").lower()
    return f"{local.strftime('%a')} {clock}" if with_day else clock


def _minutes(view: dict) -> int:
    span = datetime.fromisoformat(view["ends_at"]) - datetime.fromisoformat(view["starts_at"])
    return int(span.total_seconds() // 60)


def describe(before: list[dict], after: list[dict], batch: ActionBatch, tz: ZoneInfo):
    """Summarize a plan change as Moved/Shortened/Added/Removed rows and tag the new sessions."""
    old = {v["id"]: v for v in before if v["status"] == "planned"}
    new = {v["id"]: v for v in after if v["status"] == "planned"}
    added = sorted((v for k, v in new.items() if k not in old), key=lambda v: v["starts_at"])
    removed = sorted((v for k, v in old.items() if k not in new), key=lambda v: v["starts_at"])

    def same(a, b):
        return all(a[k] == b[k] for k in ("task_id", "obligation_id", "starts_at", "ends_at"))

    # Task edits recreate future rows; one with the same task and times is not a change.
    for view in list(added):
        twin = next((r for r in removed if same(r, view)), None)
        if twin:
            added.remove(view)
            removed.remove(twin)
    changes, tags = [], {}
    for view in added:
        # The solver gives moved work a new row, so pair it with a removed row of the same task.
        twin = next((r for r in removed if r["task_id"] and r["task_id"] == view["task_id"]), None)
        if twin:
            removed.remove(twin)
            before_m, after_m = _minutes(twin), _minutes(view)
            if after_m == before_m:
                kind = "Moved"
                detail = f"{_when(twin['starts_at'], tz)} → {_when(view['starts_at'], tz)}"
            else:
                kind = "Shortened" if after_m < before_m else "Extended"
                detail = f"{before_m} → {after_m} min at {_when(view['starts_at'], tz)}"
        else:
            kind = "Added"
            detail = f"{_when(view['starts_at'], tz)}–{_when(view['ends_at'], tz, False)}"
        tags[view["id"]] = kind
        changes.append({"kind": kind, "title": view["title"], "detail": detail})
    for view in removed:
        changes.append(
            {"kind": "Removed", "title": view["title"], "detail": _when(view["starts_at"], tz)}
        )
    scheduled = {c["title"] for c in changes}
    for action in batch.actions:
        if isinstance(action, CreateGoal):
            detail = f"{len(action.tasks)} tasks"
            changes.insert(0, {"kind": "New goal", "title": action.goal.title, "detail": detail})
        elif isinstance(action, CreateTask) and action.task.title not in scheduled:
            changes.append(
                {"kind": "Added", "title": action.task.title, "detail": "Not scheduled yet"}
            )
        elif isinstance(action, SetPreference):
            changes.append({"kind": "Updated", "title": "Preferences", "detail": "Planning hours"})
    fixed = sorted({v["title"] for v in after if v["category"] == "fixed" and v["id"] in old})
    if fixed and changes:
        changes.append(
            {"kind": "Kept", "title": ", ".join(fixed[:2]), "detail": "Fixed commitments stay put"}
        )
    for view in after:
        view["change"] = tags.get(view["id"])
    return changes


def _footer(plan: PlanResult) -> str:
    if not plan.unscheduled:
        return "Everything still fits."
    missing = sum(item.minutes for item in plan.unscheduled)
    titles = ", ".join(sorted({item.title for item in plan.unscheduled})[:2])
    return f"{missing} min of {titles} could not fit in the next week."


def _out(db: Session, row: Proposal) -> dict:
    can_undo = bool(
        row.status == "applied" and row.snapshot and row.fingerprint == fingerprint(snapshot(db))
    )
    return ProposalOut.model_validate(
        {
            "id": row.id,
            "status": row.status,
            "message": row.message,
            "title": row.title,
            "changes": row.changes,
            "footer": row.footer,
            "preview": row.preview,
            "can_undo": can_undo,
            "created_at": row.created_at,
        }
    ).model_dump(mode="json")


def _say(db: Session, mode: str, content: str, role="assistant", proposal_id=None):
    db.add(ChatMessage(role=role, content=content, mode=mode, proposal_id=proposal_id))


def propose(db: Session, data: ChatIn, settings: Settings) -> dict:
    """Interpret a request and dry-run it. Nothing changes until the proposal is applied."""
    now = utcnow()
    # Interpret before acquiring the write lock; network latency must not hold DB locks.
    batch = interpret(settings, data.message, context_for(db, now))
    clarifications = [a.question for a in batch.actions if isinstance(a, Clarify)]
    defaults = list(batch.defaults)
    if clarifications:
        reply = " ".join(clarifications)
        resources.preferences(db, lock=True)
        _say(db, settings.ai_mode, data.message, role="user")
        _say(db, settings.ai_mode, reply)
        db.flush()
        return {
            "reply": reply,
            "mode": settings.ai_mode,
            "defaults": defaults,
            "needs_clarification": True,
            "proposal": None,
        }
    tz = ZoneInfo(resources.preferences(db).timezone)
    start, end = _window(data.plan, now, tz)
    base = fingerprint(snapshot(db))
    before = _views(db, start, end)
    plan = apply_batch(db, batch, data.plan, now)
    after = _views(db, start, end)
    changes = describe(before, after, batch, tz)
    result = snapshot(db)
    # The dry run is discarded; only the reviewed proposal (and its exact outcome) is stored.
    db.rollback()
    resources.preferences(db, lock=True)
    for stale in db.scalars(select(Proposal).where(Proposal.status == "pending")):
        stale.status = "discarded"
    title = batch.explanation.strip().rstrip(".")
    footer = _footer(plan)
    if defaults:
        footer += " Assumed: " + "; ".join(defaults)
    row = Proposal(
        message=data.message,
        title=title,
        batch=batch.model_dump(mode="json"),
        plan=data.plan.model_dump(mode="json"),
        changes=changes,
        footer=footer,
        preview={"start": start.isoformat(), "end": end.isoformat(), "sessions": after},
        result=result,
        base_fingerprint=base,
    )
    db.add(row)
    db.flush()
    _say(db, settings.ai_mode, data.message, role="user", proposal_id=row.id)
    db.flush()
    return {
        "reply": title,
        "mode": settings.ai_mode,
        "defaults": defaults,
        "needs_clarification": False,
        "proposal": _out(db, row),
    }


def _pending(db: Session, identifier: UUID) -> Proposal:
    row = resources.require(db, Proposal, identifier)
    if row.status != "pending":
        raise HTTPException(409, f"This proposal was already {row.status}.")
    return row


def apply_proposal(db: Session, identifier: UUID, settings: Settings) -> dict:
    now = utcnow()
    resources.preferences(db, lock=True)
    row = _pending(db, identifier)
    batch = ActionBatch.model_validate(row.batch)
    request = PlanRequest.model_validate(row.plan)
    tz = ZoneInfo(resources.preferences(db).timezone)
    start, end = _window(request, now, tz)
    before_state = snapshot(db)
    before = _views(db, start, end)
    if row.result and row.base_fingerprint == fingerprint(before_state):
        # Nothing changed since the preview: commit exactly what was shown, without solving again.
        restore(db, row.result)
        row = resources.require(db, Proposal, identifier)
    else:
        # Something changed in between, so the preview may no longer fit; plan again.
        row.footer = _footer(apply_batch(db, batch, request, now))
    after = _views(db, start, end)
    row.changes = describe(before, after, batch, tz)
    row.preview = {"start": start.isoformat(), "end": end.isoformat(), "sessions": after}
    row.result = None
    row.status = "applied"
    row.snapshot = before_state
    row.fingerprint = fingerprint(snapshot(db))
    moved = [f"{c['title']}: {c['detail']}" for c in row.changes if c["kind"] != "Kept"]
    reply = "Done. " + ("; ".join(moved[:3]) + "." if moved else "Your plan is updated.")
    _say(db, settings.ai_mode, reply, proposal_id=row.id)
    db.flush()
    return {"reply": reply, "proposal": _out(db, row)}


def discard_proposal(db: Session, identifier: UUID, settings: Settings) -> dict:
    resources.preferences(db, lock=True)
    row = _pending(db, identifier)
    row.status = "discarded"
    reply = "Discarded. Your plan is unchanged."
    _say(db, settings.ai_mode, reply, proposal_id=row.id)
    db.flush()
    return {"reply": reply, "proposal": _out(db, row)}


def undo_proposal(db: Session, identifier: UUID, settings: Settings) -> dict:
    resources.preferences(db, lock=True)
    row = resources.require(db, Proposal, identifier)
    if row.status != "applied" or not row.snapshot:
        raise HTTPException(409, "Only an applied proposal can be undone.")
    if row.fingerprint != fingerprint(snapshot(db)):
        raise HTTPException(
            409, "Your plan has changed since this was applied, so it can no longer be undone."
        )
    restore(db, row.snapshot)
    row = resources.require(db, Proposal, identifier)
    row.status = "undone"
    reply = "Undone. Your previous plan is back."
    _say(db, settings.ai_mode, reply, proposal_id=row.id)
    db.flush()
    return {"reply": reply, "proposal": _out(db, row)}


def current_proposal(db: Session) -> dict | None:
    """What the chat panel shows: a proposal awaiting review, or the last undoable one."""
    row = db.scalar(
        select(Proposal)
        .where(Proposal.status.in_(("pending", "applied")))
        .order_by(Proposal.created_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    out = _out(db, row)
    return out if row.status == "pending" or out["can_undo"] else None

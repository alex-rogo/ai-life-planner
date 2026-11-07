from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import ChatMessage, Goal, Obligation, Proposal, ScheduleSession, Task
from app.schemas import (
    ChatIn,
    GoalOut,
    ObligationOut,
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
    DeleteObligation,
    Reply,
    Reschedule,
    SetPreference,
    UpdateObligation,
    UpdateTask,
)
from app.services.ai.interpreter import interpret, review
from app.services.history import fingerprint, restore, snapshot
from app.services.scheduler import generate_plan, local_midnight
from app.services.upkeep import session_views, sessions_between

CHANGE_MARKS = {"Added": "NEW", "Moved": "MOVED", "Shortened": "CHANGED", "Extended": "CHANGED"}


def week_text(views: list[dict], tz: ZoneInfo) -> str:
    """The plan as the assistant reads it: one line per day, marks for changes and fixed items."""
    days: dict[str, list[str]] = {}
    for v in sorted(views, key=lambda v: v["starts_at"]):
        if v["status"] not in ("planned", "completed"):
            continue
        a = datetime.fromisoformat(v["starts_at"]).astimezone(tz)
        b = datetime.fromisoformat(v["ends_at"]).astimezone(tz)
        marks = [
            m
            for m in (
                CHANGE_MARKS.get(v.get("change") or ""),
                v.get("travel") and "trip",
                not v.get("task_id") and not v.get("travel") and "fixed",
                v["status"] == "completed" and "done",
            )
            if m
        ]
        tag = f" [{', '.join(marks)}]" if marks else ""
        days.setdefault(f"{a:%a %b} {a.day}", []).append(f"{a:%H:%M}-{b:%H:%M} {v['title']}{tag}")
    return (
        "\n".join(f"{day}: " + "; ".join(rows) for day, rows in days.items()) or "Nothing planned."
    )


def context_for(db: Session, now: datetime) -> dict:
    tz = ZoneInfo(resources.preferences(db).timezone)
    local = now.astimezone(tz)
    proposals = {
        p.id: p for p in db.scalars(select(Proposal).order_by(Proposal.created_at.desc()).limit(30))
    }
    messages = reversed(
        db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(20)).all()
    )

    def said(m: ChatMessage) -> dict:
        entry = {"role": m.role, "content": m.content}
        proposal = proposals.get(m.proposal_id)
        if proposal and m.role == "user":
            entry["proposal"] = {"summary": proposal.title, "status": proposal.status}
        return entry

    start = local_midnight(local.date(), tz)
    monday = local.date() - timedelta(days=local.weekday())
    week_a, week_b = local_midnight(monday, tz), local_midnight(monday + timedelta(days=7), tz)
    habits = []
    for task in db.scalars(
        select(Task).where(Task.status == "pending", Task.recurrence == "weekly")
    ):
        planned = db.scalar(
            select(func.count(ScheduleSession.id)).where(
                ScheduleSession.task_id == task.id,
                ScheduleSession.status.in_(("planned", "completed")),
                ScheduleSession.starts_at >= week_a,
                ScheduleSession.starts_at < week_b,
            )
        )
        habits.append(
            f"{task.title}: {planned} of {task.sessions_per_week} sessions this week (Mon-Sun)"
        )
    return {
        "now": now.isoformat(),
        "today": f"{local:%A} {local.date().isoformat()}",
        "week": week_text(_views(db, start, start + timedelta(days=7)), tz),
        "habits_this_week": habits,
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
        # Unconfirmed changes, so a follow-up like "oops, X is on Tuesday" can revise them.
        "pending_proposal": next(
            (
                {"request": p.message, "actions": p.batch.get("actions", [])}
                for p in db.scalars(select(Proposal).where(Proposal.status == "pending").limit(1))
            ),
            None,
        ),
        # Existing events, so the assistant avoids duplicates and spots conflicts.
        "events": [
            ObligationOut.model_validate(o).model_dump(mode="json")
            for o in db.scalars(select(Obligation).order_by(Obligation.start_time).limit(100))
        ],
        "recent_messages": [said(m) for m in messages],
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
        elif isinstance(action, UpdateObligation):
            resources.save_obligation(db, action.obligation, action.obligation_id)
        elif isinstance(action, DeleteObligation):
            db.delete(resources.require(db, Obligation, action.obligation_id))
            db.flush()
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


def _owner(view: dict):
    return view["task_id"] or (view["obligation_id"], view["title"])


def _slots(views: list[dict], tz: ZoneInfo) -> str:
    """Sessions as days per time range: "Fri, Sat, Sun 4:00 pm-5:00 pm; Mon 7:00 pm-8:30 pm"."""
    ranges: dict[str, list[str]] = {}
    for v in sorted(views, key=lambda v: v["starts_at"]):
        span = f"{_when(v['starts_at'], tz, False)}–{_when(v['ends_at'], tz, False)}"
        day = datetime.fromisoformat(v["starts_at"]).astimezone(tz).strftime("%a")
        ranges.setdefault(span, []).append(day)
    return "; ".join(f"{', '.join(days)} {span}" for span, days in ranges.items())


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
    # The solver gives moved work new rows, so changes are grouped per task (or fixed item) and
    # described as a whole: "Fri, Sat, Sun 4:00 pm-5:00 pm (was Mon, Wed 4:00 pm-5:00 pm)".
    groups: dict = {}
    for view in added:
        groups.setdefault(_owner(view), ([], []))[0].append(view)
    for view in removed:
        groups.setdefault(_owner(view), ([], []))[1].append(view)
    for new_rows, old_rows in groups.values():
        title = (new_rows or old_rows)[0]["title"]
        if len(new_rows) == 1 and len(old_rows) == 1:
            twin, view = old_rows[0], new_rows[0]
            before_m, after_m = _minutes(twin), _minutes(view)
            if after_m == before_m:
                kind = "Moved"
                detail = f"{_when(twin['starts_at'], tz)} → {_when(view['starts_at'], tz)}"
            else:
                kind = "Shortened" if after_m < before_m else "Extended"
                detail = f"{before_m} → {after_m} min at {_when(view['starts_at'], tz)}"
        elif new_rows and old_rows:
            kind = "Moved"
            detail = f"{_slots(new_rows, tz)} (was {_slots(old_rows, tz)})"
        elif new_rows:
            kind, detail = "Added", _slots(new_rows, tz)
        else:
            kind, detail = "Removed", _slots(old_rows, tz)
        for view in new_rows:
            tags[view["id"]] = kind
        changes.append({"kind": kind, "title": title, "detail": detail})
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


def _say(db: Session, mode: str, content: str, role="assistant", proposal_id=None, options=None):
    db.add(
        ChatMessage(
            role=role, content=content, mode=mode, proposal_id=proposal_id, options=options or None
        )
    )


def propose(db: Session, data: ChatIn, settings: Settings) -> dict:
    """Interpret a request and dry-run it. Nothing changes until the proposal is applied."""
    now = utcnow()
    # Interpret before acquiring the write lock; network latency must not hold DB locks.
    context = context_for(db, now)
    batch = interpret(settings, data.message, context)
    said = [
        a.question if isinstance(a, Clarify) else a.message
        for a in batch.actions
        if isinstance(a, (Clarify, Reply))
    ]
    work = [a for a in batch.actions if not isinstance(a, (Clarify, Reply))]
    defaults = list(batch.defaults)
    if said and work and not any(isinstance(a, Clarify) for a in batch.actions):
        # Talk alongside changes becomes part of the proposal instead of being lost.
        batch = batch.model_copy(
            update={"actions": work, "explanation": " ".join([batch.explanation, *said])[:2000]}
        )
        said = []
    if said:
        reply = "\n\n".join(said)
        options = [o for a in batch.actions if isinstance(a, (Clarify, Reply)) for o in a.options][
            :4
        ]
        resources.preferences(db, lock=True)
        _say(db, settings.ai_mode, data.message, role="user")
        _say(db, settings.ai_mode, reply, options=options)
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

    def dry_run(candidate: ActionBatch):
        plan = apply_batch(db, candidate, data.plan, now)
        after = _views(db, start, end)
        return plan, after, describe(before, after, candidate, tz)

    plan, after, changes = dry_run(batch)
    # The assistant checks the week its proposal actually produces, and may revise it once.
    missing = [f"{u.title}: {u.minutes} min ({u.reason})" for u in plan.unscheduled]
    verdict = review(settings, data.message, context, batch, week_text(after, tz), missing)
    if verdict and verdict.verdict == "revise" and verdict.revised:
        revised = [a for a in verdict.revised.actions if not isinstance(a, (Clarify, Reply))]
        if revised:
            db.rollback()
            batch = verdict.revised.model_copy(update={"actions": revised})
            defaults = list(batch.defaults)
            plan, after, changes = dry_run(batch)
    result = snapshot(db)
    # The dry run is discarded; only the reviewed proposal (and its exact outcome) is stored.
    db.rollback()
    resources.preferences(db, lock=True)
    for stale in db.scalars(select(Proposal).where(Proposal.status == "pending")):
        stale.status = "discarded"
    title = (verdict.summary if verdict else batch.explanation).strip().rstrip(
        "."
    ) or "Proposed changes"
    footer = _footer(plan)
    if verdict and verdict.concerns:
        footer += " Heads up: " + " ".join(c.strip().rstrip(".") + "." for c in verdict.concerns)
    # A reviewed proposal's summary already explains its choices; the raw assumptions would only
    # repeat it at length.
    if defaults and not verdict:
        footer += " Assumed: " + "; ".join(defaults)
    row = Proposal(
        message=data.message,
        title=title,
        # Only what the assistant actually set: re-running a stored edit must not reset the
        # fields it left alone.
        batch=batch.model_dump(mode="json", exclude_unset=True),
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
    reply = f"Done. {row.title}." if row.title else "Done. Your plan is updated."
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

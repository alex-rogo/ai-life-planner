"""A bounded, deterministic CP-SAT planner; no language model makes scheduling decisions."""

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from itertools import combinations
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from ortools.sat.python import cp_model
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Obligation, ScheduleSession, Task
from app.schemas import PlanRequest, PlanResult, SessionOut, Unscheduled
from app.services.resources import preferences

SLOT = timedelta(minutes=15)
MAX_UNITS = 100


@dataclass
class Unit:
    task: Task
    minutes: int
    earliest: datetime
    latest: datetime
    previous: ScheduleSession | None = None
    group: str = ""


def local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def clock_minutes(value: str) -> int:
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def in_window(minute: int, start: str, end: str) -> bool:
    a, b = clock_minutes(start), clock_minutes(end)
    return a <= minute < b if a < b else minute >= a or minute < b


def work_allowed(stamp: datetime, prefs, tz: ZoneInfo) -> bool:
    local = stamp.astimezone(tz)
    minute = local.hour * 60 + local.minute
    return in_window(minute, prefs.available_start, prefs.available_end) and not in_window(
        minute, prefs.sleep_start, prefs.sleep_end
    )


def expand_obligations(obligations, start, end, tz):
    result = []
    day = start.astimezone(tz).date()
    while local_midnight(day, tz) < end:
        for obligation in obligations:
            if day.weekday() not in obligation.weekdays:
                continue
            if obligation.start_date and day.isoformat() < obligation.start_date:
                continue
            if obligation.end_date and day.isoformat() > obligation.end_date:
                continue
            a = datetime.combine(day, time.fromisoformat(obligation.start_time), tzinfo=tz)
            b = datetime.combine(day, time.fromisoformat(obligation.end_time), tzinfo=tz)
            # A nonexistent wall clock time must not silently become a different appointment.
            if any(
                x.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != x.replace(tzinfo=None)
                for x in (a, b)
            ):
                raise HTTPException(409, f"{obligation.title} falls in a daylight-saving gap")
            a, b = a.astimezone(UTC), b.astimezone(UTC)
            if a < end and b > start:
                result.append(
                    ScheduleSession(
                        obligation_id=obligation.id,
                        title=obligation.title,
                        starts_at=a,
                        ends_at=b,
                        locked=True,
                        status="planned",
                        credited_minutes=0,
                    )
                )
        day += timedelta(days=1)
    return result


def partition(minutes: int, minimum: int, maximum: int) -> list[int]:
    """Balanced chunks avoid a final remainder shorter than the minimum session."""
    slots = math.ceil(minutes / 15)
    count = math.ceil(slots / (maximum // 15))
    if count > slots // (minimum // 15):
        return []
    base, extra = divmod(slots, count)
    return [(base + (i < extra)) * 15 for i in range(count)]


def make_units(tasks, history, start, end, tz, old):
    units, unfit = [], []
    day_start = start.astimezone(tz).date()
    by_task = defaultdict(list)
    for session in history:
        if session.task_id:
            by_task[session.task_id].append(session)
    old_by_task = defaultdict(list)
    for session in sorted(old, key=lambda x: x.starts_at):
        if session.task_id:
            old_by_task[session.task_id].append(session)

    for task in tasks:
        earliest = max(start, task.created_at, task.not_before or start)
        latest = min(end, task.deadline or end)
        kept = [s for s in by_task[task.id] if s.status in ("planned", "completed")]
        windows = []
        if task.recurrence == "none":
            reserved = sum(
                int((s.ends_at - s.starts_at).total_seconds() // 60)
                for s in kept
                if s.status == "planned"
            )
            remaining = max(0, task.duration_minutes - task.completed_minutes - reserved)
            if remaining:
                chunks = partition(remaining, task.min_session_minutes, task.max_session_minutes)
                if not chunks:
                    unfit.append(
                        Unscheduled(
                            task_id=task.id,
                            title=task.title,
                            minutes=remaining,
                            reason="Remaining work cannot be split within the session limits.",
                        )
                    )
                windows = [(earliest, latest, chunk, "") for chunk in chunks]
        else:
            # Count user-confirmed minutes, not merely completed row count. A shortened
            # recurring session leaves work to plan in its calendar day/week.
            period = (
                day_start
                if task.recurrence == "daily"
                else day_start - timedelta(days=day_start.weekday())
            )
            period_days = 1 if task.recurrence == "daily" else 7
            while local_midnight(period, tz) < end:
                a = local_midnight(period, tz)
                b = local_midnight(period + timedelta(days=period_days), tz)
                relevant = [s for s in kept if a <= s.starts_at < b]
                accounted = sum(
                    s.credited_minutes
                    if s.status == "completed"
                    else int((s.ends_at - s.starts_at).total_seconds() // 60)
                    for s in relevant
                )
                target = task.duration_minutes * (1 if period_days == 1 else task.sessions_per_week)
                remaining = max(0, target - accounted)
                chunks = (
                    partition(remaining, task.min_session_minutes, task.duration_minutes)
                    if remaining
                    else []
                )
                if remaining and not chunks:
                    unfit.append(
                        Unscheduled(
                            task_id=task.id,
                            title=task.title,
                            minutes=remaining,
                            reason="Remaining recurrence cannot fit the minimum session length.",
                        )
                    )
                for chunk in chunks:
                    windows.append((max(earliest, a), min(latest, b), chunk, period.isoformat()))
                period += timedelta(days=period_days)
        previous = list(old_by_task[task.id])
        for index, (a, b, duration, group) in enumerate(windows):
            match = next(
                (
                    p
                    for p in previous
                    if a <= p.starts_at < b
                    and int((p.ends_at - p.starts_at).total_seconds() // 60) == duration
                ),
                None,
            )
            if match:
                previous.remove(match)
            units.append(Unit(task, duration, a, b, match, group))
    return units, unfit


def solve(units, fixed, start, end, prefs, tz):
    model = cp_model.CpModel()
    horizon = math.ceil((end - start) / SLOT)
    intervals, decisions, penalties = [], [], []
    occupied = []
    # Fixed blocks filter feasible start domains using their exact timestamps.
    # Rounding appointments outward would incorrectly conflict at shared slot edges.
    occupied = [(session.starts_at, session.ends_at) for session in fixed]
    allowed = [
        all(work_allowed(start + slot * SLOT + timedelta(minutes=m), prefs, tz) for m in range(15))
        for slot in range(horizon)
    ]
    for i, unit in enumerate(units):
        size = unit.minutes // 15
        candidates, days = [], []
        for slot in range(horizon - size + 1):
            a, b = start + slot * SLOT, start + (slot + size) * SLOT
            if a < unit.earliest or b > unit.latest:
                continue
            if not all(allowed[slot : slot + size]):
                continue
            if a.astimezone(tz).date() != (b - timedelta(microseconds=1)).astimezone(tz).date():
                continue
            if any(a < y and b > x for x, y in occupied):
                continue
            candidates.append(slot)
            days.append((a.astimezone(tz).date() - start.astimezone(tz).date()).days)
        if not candidates:
            decisions.append(None)
            continue
        present = model.new_bool_var(f"present_{i}")
        begin = model.new_int_var_from_domain(cp_model.Domain.from_values(candidates), f"start_{i}")
        finish = model.new_int_var(0, horizon + size, f"end_{i}")
        day = model.new_int_var(0, 14, f"day_{i}")
        model.add(finish == begin + size)
        intervals.append(model.new_optional_interval_var(begin, size, finish, present, f"work_{i}"))
        # A handful of per-day selectors avoids one Boolean per candidate start.
        # Preferred-hours penalties are distance outside the local preferred window.
        early = model.new_int_var(0, horizon + 192, f"early_{i}")
        late = model.new_int_var(0, horizon + 192, f"late_{i}")
        selectors = []
        day_terms = []
        for local_day in sorted(set(days)):
            selector = model.new_bool_var(f"day_{i}_{local_day}")
            selectors.append(selector)
            day_terms.append(local_day * selector)
            slots = [slot for slot, d in zip(candidates, days) if d == local_day]
            model.add(begin >= min(slots)).only_enforce_if(selector)
            model.add(begin <= max(slots)).only_enforce_if(selector)
            calendar_day = start.astimezone(tz).date() + timedelta(days=local_day)
            pref_a = datetime.combine(
                calendar_day, time.fromisoformat(prefs.preferred_start), tzinfo=tz
            ).astimezone(UTC)
            pref_b = datetime.combine(
                calendar_day, time.fromisoformat(prefs.preferred_end), tzinfo=tz
            ).astimezone(UTC)
            model.add(early >= math.ceil((pref_a - start) / SLOT) - begin).only_enforce_if(selector)
            model.add(late >= finish - math.floor((pref_b - start) / SLOT)).only_enforce_if(
                selector
            )
        model.add(sum(selectors) == present)
        model.add(day == sum(day_terms))
        model.add(early == 0).only_enforce_if(present.Not())
        model.add(late == 0).only_enforce_if(present.Not())
        earliness = model.new_int_var(0, horizon, f"earliness_{i}")
        model.add(earliness == begin).only_enforce_if(present)
        model.add(earliness == 0).only_enforce_if(present.Not())
        penalties.extend(
            [earliness * unit.task.priority, (early + late) * prefs.preferred_weight * 12]
        )
        if unit.previous:
            old_slot = int((unit.previous.starts_at - start) / SLOT)
            displacement = model.new_int_var(0, horizon * 2, f"displacement_{i}")
            model.add(displacement >= begin - old_slot).only_enforce_if(present)
            model.add(displacement >= old_slot - begin).only_enforce_if(present)
            model.add(displacement == 0).only_enforce_if(present.Not())
            penalties.append(displacement * prefs.stability_weight * 12)
            if old_slot in candidates:
                model.add_hint(present, 1)
                model.add_hint(begin, old_slot)
        decisions.append((present, begin, finish, day))
    model.add_no_overlap(intervals)

    for i, j in combinations(range(len(units)), 2):
        left, right = decisions[i], decisions[j]
        if left is None or right is None:
            continue
        p, a, b, day_a = left
        q, c, d, day_b = right
        gap = prefs.break_minutes // 15
        # Soft recovery gaps: relaxing a break is permitted, relaxing overlap never is.
        if gap and (units[i].minutes >= 60 or units[j].minutes >= 60):
            before = model.new_bool_var(f"order_{i}_{j}")
            relaxed = model.new_bool_var(f"no_break_{i}_{j}")
            model.add(b + gap <= c).only_enforce_if([p, q, before, relaxed.Not()])
            model.add(d + gap <= a).only_enforce_if([p, q, before.Not(), relaxed.Not()])
            penalties.append(relaxed * prefs.break_weight * 12)
        if units[i].task.id != units[j].task.id and prefs.context_weight:
            distant = model.new_bool_var(f"separate_{i}_{j}")
            order = model.new_bool_var(f"context_order_{i}_{j}")
            model.add(b + 1 <= c).only_enforce_if([p, q, order, distant])
            model.add(d + 1 <= a).only_enforce_if([p, q, order.Not(), distant])
            penalties.append((1 - distant) * prefs.context_weight * 12)
        if (
            units[i].task.id == units[j].task.id
            and units[i].task.recurrence == "weekly"
            and units[i].group == units[j].group
        ):
            same = model.new_bool_var(f"same_day_{i}_{j}")
            model.add(day_a != day_b).only_enforce_if([p, q, same.Not()])
            penalties.append(same * prefs.spread_weight * 100)
            # Symmetry breaking makes identical weekly occurrences cheaper to solve.
            model.add(a < c).only_enforce_if([p, q])
    # This coefficient dominates the maximum bounded secondary penalty, so
    # tuning preferences cannot accidentally outweigh priority-weighted coverage.
    n = len(units)
    secondary_bound = n * (
        horizon * (5 + 24 * prefs.stability_weight) + (horizon + 192) * 24 * prefs.preferred_weight
    )
    secondary_bound += (
        n
        * (n - 1)
        // 2
        * (12 * prefs.break_weight + 12 * prefs.context_weight + 100 * prefs.spread_weight)
    )
    reward = sum(
        d[0] * u.minutes * (u.task.priority + 1) * (secondary_bound + 1)
        for u, d in zip(units, decisions)
        if d
    )
    model.maximize(reward - sum(penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 8
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    label = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise HTTPException(
            409,
            f"Schedule {label.lower()}: fixed/locked blocks conflict or solver could not find a plan. Existing schedule retained.",
        )
    return solver, decisions, label


def generate_plan(db: Session, request: PlanRequest, now: datetime | None = None) -> PlanResult:
    prefs = preferences(db, lock=True)
    tz = ZoneInfo(prefs.timezone)
    now = now or utcnow()
    first = request.start_date or now.astimezone(tz).date()
    day_begin = local_midnight(first, tz)
    end = local_midnight(first + timedelta(days=request.days), tz)
    if end <= now:
        raise HTTPException(422, "Planning horizon must include future time")
    # Round the current instant up, anchored to UTC quarters.
    start = max(day_begin, datetime.fromtimestamp(math.ceil(now.timestamp() / 900) * 900, UTC))
    all_sessions = db.scalars(select(ScheduleSession).order_by(ScheduleSession.starts_at)).all()
    old = [
        s
        for s in all_sessions
        if s.starts_at >= start
        and s.starts_at < end
        and s.status == "planned"
        and not s.locked
        and s.task_id
    ]
    old_ids = {s.id for s in old}
    persisted_fixed = [
        s
        for s in all_sessions
        if s.id not in old_ids
        and s.starts_at < end
        and s.ends_at > start
        and s.status in ("planned", "completed")
    ]
    for session in persisted_fixed:
        if not session.task_id or session.status != "planned" or session.starts_at < start:
            continue
        task = db.get(Task, session.task_id)
        duration = int((session.ends_at - session.starts_at).total_seconds() // 60)
        if (
            task.deadline
            and session.ends_at > task.deadline
            or task.not_before
            and session.starts_at < task.not_before
            or not task.min_session_minutes <= duration <= task.max_session_minutes
            or not all(
                work_allowed(session.starts_at + timedelta(minutes=m), prefs, tz)
                for m in range(duration)
            )
        ):
            raise HTTPException(
                409,
                f"Protected session {session.title} conflicts with current constraints. Unlock or resolve it first.",
            )
    obligations = db.scalars(select(Obligation)).all()
    fixed = list(persisted_fixed)
    existing_keys = {(s.obligation_id, s.starts_at) for s in all_sessions if s.obligation_id}
    new_obligations = []
    for item in expand_obligations(obligations, day_begin, end, tz):
        if (item.obligation_id, item.starts_at) not in existing_keys:
            new_obligations.append(item)
            if item.ends_at > start:
                fixed.append(item)
    # Reject overlapping fixed blocks rather than treating solver infeasibility as missing work.
    ordered = sorted(fixed, key=lambda x: x.starts_at)
    for left, right in zip(ordered, ordered[1:]):
        if left.ends_at > right.starts_at:
            raise HTTPException(
                409,
                f"Fixed blocks conflict: {left.title} and {right.title}. Existing schedule retained.",
            )
    tasks = db.scalars(select(Task).where(Task.status == "pending").order_by(Task.id)).all()
    history = [s for s in all_sessions if s.id not in old_ids]
    units, unfit = make_units(tasks, history, start, end, tz, old)
    if len(units) > MAX_UNITS:
        raise HTTPException(
            422, "More than 100 work sessions requested. Reduce the horizon or active tasks."
        )
    solver, decisions, status = solve(units, fixed, start, end, prefs, tz)
    replacements = []
    reused = set()
    for unit, decision in zip(units, decisions):
        if decision is None or not solver.value(decision[0]):
            reason = (
                "No contiguous time fits availability, sleep, fixed blocks, earliest start and deadline."
                if decision is None
                else "Available capacity was allocated to higher-value work."
            )
            unfit.append(
                Unscheduled(
                    task_id=unit.task.id, title=unit.task.title, minutes=unit.minutes, reason=reason
                )
            )
            continue
        a = start + solver.value(decision[1]) * SLOT
        b = start + solver.value(decision[2]) * SLOT
        # Preserve row identity on a stable plan; suggestions remain associated with that row.
        previous = unit.previous
        if previous and previous.starts_at == a and previous.ends_at == b:
            reused.add(previous.id)
        else:
            replacements.append(
                ScheduleSession(
                    task_id=unit.task.id,
                    title=unit.task.title,
                    starts_at=a,
                    ends_at=b,
                    status="planned",
                    locked=False,
                    credited_minutes=0,
                )
            )
    removed = old_ids - reused
    if removed:
        db.execute(delete(ScheduleSession).where(ScheduleSession.id.in_(removed)))
    db.add_all(new_obligations + replacements)
    db.flush()
    sessions = db.scalars(
        select(ScheduleSession)
        .where(ScheduleSession.starts_at < end, ScheduleSession.ends_at > day_begin)
        .order_by(ScheduleSession.starts_at)
    ).all()
    return PlanResult(
        sessions=[SessionOut.model_validate(s) for s in sessions],
        unscheduled=unfit,
        solver_status=status,
        explanation=(
            f"Planned {len(replacements) + len(reused)} flexible sessions. "
            f"{sum(item.minutes for item in unfit)} minutes could not fit. "
            "Fixed, locked, completed and in-progress blocks were preserved."
        ),
    )

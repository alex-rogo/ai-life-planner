import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


Title = Annotated[str, Field(min_length=1, max_length=200)]
Minutes = Annotated[int, Field(ge=15, le=10080, multiple_of=15)]
Clock = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]


class GoalCreate(Schema):
    title: Title
    description: str = Field(default="", max_length=4000)
    deadline: AwareDatetime | None = None


class GoalOut(GoalCreate):
    id: UUID
    created_at: datetime


class TaskCreate(Schema):
    title: Title
    description: str = Field(default="", max_length=4000)
    goal_id: UUID | None = None
    duration_minutes: Minutes = 60
    priority: int = Field(default=3, ge=1, le=5)
    status: Literal["pending", "completed", "cancelled"] = "pending"
    deadline: AwareDatetime | None = None
    not_before: AwareDatetime | None = None
    min_session_minutes: Minutes = 30
    max_session_minutes: Minutes = 90
    recurrence: Literal["none", "daily", "weekly"] = "none"
    sessions_per_week: int = Field(default=3, ge=1, le=7)
    activity_apps: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(
        default_factory=list, max_length=20
    )

    @field_validator("activity_apps")
    @classmethod
    def normalize_apps(cls, value):
        if any(not re.fullmatch(r"[\w .+()-]+\.exe", app, re.I) for app in value):
            raise ValueError("Use executable basenames such as Code.exe")
        return sorted(set(app.lower() for app in value))

    @model_validator(mode="after")
    def session_bounds(self):
        if self.min_session_minutes > self.max_session_minutes:
            raise ValueError("Minimum session length must not exceed maximum")
        if self.duration_minutes < self.min_session_minutes:
            raise ValueError("Task duration must fit at least one minimum session")
        if self.recurrence != "none" and self.duration_minutes > self.max_session_minutes:
            raise ValueError("A recurring occurrence must fit one session")
        if self.not_before and self.deadline and self.not_before >= self.deadline:
            raise ValueError("Earliest start must precede deadline")
        return self


class TaskPatch(Schema):
    title: Title | None = None
    description: str | None = Field(default=None, max_length=4000)
    goal_id: UUID | None = None
    duration_minutes: Minutes | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: Literal["pending", "completed", "cancelled"] | None = None
    deadline: AwareDatetime | None = None
    not_before: AwareDatetime | None = None
    min_session_minutes: Minutes | None = None
    max_session_minutes: Minutes | None = None
    recurrence: Literal["none", "daily", "weekly"] | None = None
    sessions_per_week: int | None = Field(default=None, ge=1, le=7)
    activity_apps: list[str] | None = None


class TaskOut(TaskCreate):
    id: UUID
    completed_minutes: int
    created_at: datetime


class ObligationCreate(Schema):
    title: Title
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(min_length=1, max_length=7)
    start_time: Clock
    end_time: Clock
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.start_time >= self.end_time:
            raise ValueError("Obligations must start and end on the same day")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Weekdays must be unique")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date must precede end date")
        return self


class ObligationOut(ObligationCreate):
    id: UUID


class Preferences(Schema):
    timezone: str = "America/Los_Angeles"
    sleep_start: Clock = "23:00"
    sleep_end: Clock = "07:00"
    available_start: Clock = "07:00"
    available_end: Clock = "23:00"
    preferred_start: Clock = "09:00"
    preferred_end: Clock = "17:00"
    break_minutes: int = Field(default=15, ge=0, le=60, multiple_of=15)
    stability_weight: int = Field(default=8, ge=0, le=100)
    preferred_weight: int = Field(default=3, ge=0, le=100)
    break_weight: int = Field(default=10, ge=0, le=100)
    context_weight: int = Field(default=5, ge=0, le=100)
    spread_weight: int = Field(default=20, ge=0, le=100)
    monitoring_enabled: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def windows(self):
        if self.available_start >= self.available_end or self.preferred_start >= self.preferred_end:
            raise ValueError("Availability and preferred hours must be same-day increasing windows")
        if self.sleep_start == self.sleep_end:
            raise ValueError("Sleep window must have a nonzero duration")
        return self


class PlanRequest(Schema):
    start_date: date | None = None
    days: int = Field(default=7, ge=1, le=14)


class SessionOut(Schema):
    id: UUID
    task_id: UUID | None
    obligation_id: UUID | None
    title: str
    starts_at: datetime
    ends_at: datetime
    status: str
    locked: bool
    credited_minutes: int


class SessionPatch(Schema):
    status: Literal["completed", "skipped", "missed"] | None = None
    locked: bool | None = None
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)


class Unscheduled(Schema):
    task_id: UUID
    title: str
    minutes: int
    reason: str


class PlanResult(Schema):
    sessions: list[SessionOut]
    unscheduled: list[Unscheduled]
    solver_status: str
    explanation: str


class ActivityIn(Schema):
    id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    app_name: str | None = Field(default=None, max_length=120)
    state: Literal["active", "idle", "unknown"]
    idle_seconds: int = Field(ge=0, le=604800)

    @model_validator(mode="after")
    def bounds(self):
        seconds = (self.ends_at - self.starts_at).total_seconds()
        if seconds <= 0 or seconds > 300:
            raise ValueError("Activity reports must describe at most five minutes")
        if self.app_name and ("/" in self.app_name or "\\" in self.app_name):
            raise ValueError("Only application basenames are accepted")
        return self


class ActivityBatch(Schema):
    events: list[ActivityIn] = Field(min_length=1, max_length=100)


class SuggestionOut(Schema):
    id: UUID
    session_id: UUID
    message: str
    remaining_minutes: int
    status: str
    created_at: datetime


class SuggestionDecision(Schema):
    decision: Literal["confirm", "dismiss"]


class ChatIn(Schema):
    message: str = Field(min_length=1, max_length=4000)
    plan: PlanRequest = Field(default_factory=PlanRequest)


class MessageOut(Schema):
    id: UUID
    role: str
    content: str
    mode: str
    created_at: datetime

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas import GoalCreate, ObligationCreate, Preferences, Schema, TaskCreate, TaskPatch


class CreateGoal(Schema):
    kind: Literal["create_goal"]
    goal: GoalCreate
    tasks: list[TaskCreate] = Field(min_length=1, max_length=12)


class CreateTask(Schema):
    kind: Literal["create_task"]
    task: TaskCreate


class UpdateTask(Schema):
    kind: Literal["update_task"]
    task_id: UUID
    changes: TaskPatch


class CreateObligation(Schema):
    kind: Literal["create_obligation"]
    obligation: ObligationCreate


class SetPreference(Schema):
    kind: Literal["set_preference"]
    preferences: Preferences


class Reschedule(Schema):
    kind: Literal["reschedule"]
    task_id: UUID | None = None
    delay_minutes: int = Field(default=0, ge=0, le=10080)
    tonight: bool = False
    priority: int | None = Field(default=None, ge=1, le=5)


class CompleteTask(Schema):
    kind: Literal["complete_task"]
    task_id: UUID
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)


class Clarify(Schema):
    kind: Literal["clarify"]
    question: str = Field(min_length=1, max_length=1000)


Action = Annotated[
    CreateGoal
    | CreateTask
    | UpdateTask
    | CreateObligation
    | SetPreference
    | Reschedule
    | CompleteTask
    | Clarify,
    Field(discriminator="kind"),
]


class ActionBatch(Schema):
    actions: list[Action] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1, max_length=2000)
    defaults: list[str] = Field(default_factory=list, max_length=12)

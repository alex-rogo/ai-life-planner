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


class UpdateObligation(Schema):
    kind: Literal["update_obligation"]
    obligation_id: UUID
    obligation: ObligationCreate


class DeleteObligation(Schema):
    kind: Literal["delete_obligation"]
    obligation_id: UUID


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
    # Tappable answers shown as buttons under the message, each written as the user's reply.
    options: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=4
    )


class Reply(Schema):
    """Talk without changing anything: answers, advice, options."""

    kind: Literal["reply"]
    message: str = Field(min_length=1, max_length=4000)
    # Tappable answers shown as buttons under the message, each written as the user's reply.
    options: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=4
    )


Action = Annotated[
    CreateGoal
    | CreateTask
    | UpdateTask
    | CreateObligation
    | UpdateObligation
    | DeleteObligation
    | SetPreference
    | Reschedule
    | CompleteTask
    | Clarify
    | Reply,
    Field(discriminator="kind"),
]


class ActionBatch(Schema):
    actions: list[Action] = Field(min_length=1, max_length=12)
    explanation: str = Field(default="", max_length=2000)
    defaults: list[str] = Field(default_factory=list, max_length=12)

"""Progress events a run emits: the CLI renders them as a progress bar, the local app streams them (SSE),
the browser engine posts them to the UI thread. Part of the JSON contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RunStarted(BaseModel):
    type: Literal["run_started"] = "run_started"
    run_id: str
    total: int
    pending: int


class TrialStarted(BaseModel):
    type: Literal["trial_started"] = "trial_started"
    trial_id: str
    scenario: str
    config: str
    task_id: str
    repeat: int


class TrialFinished(BaseModel):
    type: Literal["trial_finished"] = "trial_finished"
    trial_id: str
    scenario: str
    config: str
    task_id: str
    repeat: int
    status: str
    passed: bool
    duration_s: float
    cost_usd: float
    done: int
    total: int


class BudgetExceeded(BaseModel):
    type: Literal["budget_exceeded"] = "budget_exceeded"
    spent_usd: float
    limit_usd: float


class RunFinished(BaseModel):
    type: Literal["run_finished"] = "run_finished"
    run_id: str
    spent_usd: float
    stopped_early: bool


RunEvent = Annotated[
    RunStarted | TrialStarted | TrialFinished | BudgetExceeded | RunFinished, Field(discriminator="type")
]
EventSink = Callable[[RunEvent], None]


def ignore(event: RunEvent) -> None:
    """Default sink."""

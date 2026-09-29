"""Progress events a run emits: the CLI renders them as a progress bar, the local app streams them (SSE),
the browser engine posts them to the UI thread. Part of the JSON contracts.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RunStarted(BaseModel):
    type: Literal["run_started"] = "run_started"
    run_id: str
    total: int
    pending: int
    started_at: float = Field(default_factory=time.time, description="unix time")


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


class RunProgress(BaseModel):
    """Where a live run stands, from its events (the Runs list and the navigation badge show it)."""

    total: int = Field(description="trials to run in this session (finished ones of a resumed run excluded)")
    done: int
    running: int
    queued: int
    passed: int
    errors: int
    spent_usd: float
    started_at: float | None = Field(default=None, description="unix time")
    finished: bool = False


def progress(events: Iterable[RunEvent]) -> RunProgress:
    total = done = running = passed = errors = 0
    spent, started_at, finished = 0.0, None, False
    for event in events:
        if isinstance(event, RunStarted):
            total, started_at = event.pending, event.started_at
        elif isinstance(event, TrialStarted):
            running += 1
        elif isinstance(event, TrialFinished):
            done, running = done + 1, max(0, running - 1)
            passed += event.passed
            errors += event.status != "ok"
            spent += event.cost_usd
        elif isinstance(event, RunFinished):
            finished, spent, running = True, event.spent_usd, 0
    queued = 0 if finished else max(0, total - done - running)
    return RunProgress(total=total, done=done, running=running, queued=queued, passed=passed, errors=errors,
                       spent_usd=spent, started_at=started_at, finished=finished)  # fmt: skip

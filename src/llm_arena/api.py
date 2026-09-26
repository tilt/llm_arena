"""Request/response models of the app API (local server and browser worker). Exported as JSON Schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from llm_arena.runner.config import ExperimentConfig
from llm_arena.service import RuntimeInfo

KeySource = Literal["env", "session", "missing"]


class StartRun(BaseModel):
    experiment: ExperimentConfig
    live: bool = False
    run_id: str | None = None


class RunStartedResponse(BaseModel):
    run_id: str


class RunListing(BaseModel):
    run_id: str
    name: str
    created_at: str
    trials: int
    passed: int
    errors: int
    active: bool


class SetKey(BaseModel):
    key: str


class RuntimeResponse(RuntimeInfo):
    keys: dict[str, KeySource]

"""Request/response models of the app API (local server and browser worker). Exported as JSON Schemas."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import RunProgress
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
    scenarios: list[str] = Field(default_factory=list)
    progress: RunProgress | None = Field(default=None, description="live runs: trials done, running, queued, spend")


class SetKey(BaseModel):
    key: str


class RuntimeResponse(RuntimeInfo):
    keys: dict[str, KeySource]
    ui_build: str = Field(default="", description="build id of the web UI when the server started ('' if none)")


def run_listing(run_id: str, run: dict[str, Any], trials: list[dict[str, Any]]) -> RunListing:
    config = json.loads(run.get("config_json") or "{}")
    return RunListing(
        run_id=run_id,
        name=str(run.get("name", "")),
        created_at=str(run.get("created_at", ""))[:19],
        trials=len(trials),
        passed=sum(bool(t["passed"]) for t in trials),
        errors=sum(t["status"] != "ok" for t in trials),
        active=False,
        scenarios=list(config.get("scenarios", [])),
    )

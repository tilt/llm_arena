"""Request/response models of the app API (local server and browser worker). Exported as JSON Schemas."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_arena.llm.spec import Capabilities, Endpoint
from llm_arena.runner.config import ExperimentConfig
from llm_arena.runner.events import RunProgress
from llm_arena.runner.run import valid_run_id
from llm_arena.service import RuntimeInfo

KeySource = Literal["env", "session", "missing"]


class StartRun(BaseModel):
    experiment: ExperimentConfig
    live: bool = False
    run_id: str | None = None

    @field_validator("run_id")
    @classmethod
    def _valid_run_id(cls, value: str | None) -> str | None:
        if value is not None and not valid_run_id(value):
            raise ValueError("run ids must start with a letter or digit and use at most 121 letters, digits, ., _ or -")
        return value


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


class SaveEndpoint(BaseModel):
    """An endpoint as the app edits it. The id comes from the path; the key env var is not editable here, so a page
    cannot point an existing key (say OPENAI_API_KEY) at a host of its choosing."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    capabilities: Capabilities = Field(default_factory=Capabilities)
    input_cost_per_mtok: float = Field(default=0.0, ge=0)
    output_cost_per_mtok: float = Field(default=0.0, ge=0)
    concurrency: int | None = Field(default=None, ge=1)
    key: str | None = Field(default=None, description="optional; held in memory for this session only")
    salt: str | None = Field(
        default=None, description="keep the endpoint's identity (browser mode restores a remembered endpoint with it)"
    )


class EndpointView(Endpoint):
    """An endpoint plus where its key comes from; never the key itself."""

    key: KeySource


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

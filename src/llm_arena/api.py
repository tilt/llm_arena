"""Request/response models of the app API (local server and browser worker). Exported as JSON Schemas."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_arena.claims import Swap
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


class ClaimDraftRequest(BaseModel):
    """Share as claim: the "compare as" names for the run's self-hosted models; `config` picks one setup of a
    Beat-this run (Share my variant)."""

    model_config = ConfigDict(extra="forbid")

    names: dict[str, str] = Field(default_factory=dict, max_length=32)
    config: str | None = Field(default=None, max_length=200)


class ReproDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=256 * 1024, description="the claim JSON")
    seen: list[int] = Field(default_factory=list, max_length=300, description="comment ids counted at post time")


class ClaimExperimentRequest(BaseModel):
    """What Beat this runs: the claim, the visitor's own models for its self-hosted roles, an optional swap."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=256 * 1024)
    local: dict[str, str] = Field(default_factory=dict, max_length=16, description="role -> your model reference")
    judge_local: str | None = Field(default=None, max_length=300)
    swap: Swap | None = None
    cap_usd: float | None = Field(default=None, ge=0, le=10_000)
    gist_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{20,32}$")
    revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    declared_names: dict[str, str] = Field(default_factory=dict, max_length=32)


class CandidatesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=256 * 1024)
    role: str = Field(max_length=64)
    names: dict[str, str] = Field(default_factory=dict, max_length=64)


class Candidate(BaseModel):
    ref: str
    problem: str | None = Field(default=None, description="why it can't be this role's candidate (None: it can)")


class ThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=256 * 1024)
    comments: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    author: str = Field(max_length=100)
    total: int | None = Field(default=None, ge=0)
    engine: Literal["pages", "local"] | None = None


class GistUser(BaseModel):
    login: str


class GistComment(BaseModel):
    id: int
    user: GistUser
    created_at: str
    updated_at: str
    body: str
    html_url: str = ""


class GistClaim(BaseModel):
    """A claim file at a pinned gist revision, with what the claim page shows around it."""

    claim: str
    owner: str
    head_revision: str = Field(description="the gist's newest revision (differs: edited since the link was shared)")
    comments: int = Field(description="how many comments the gist has (more than 300: the thread loads partially)")
    html_url: str = ""


class CreateClaimGist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(max_length=256 * 1024)


class CreatedGist(BaseModel):
    gist_id: str
    revision: str
    html_url: str
    owner: str


class PostComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=65_536)


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

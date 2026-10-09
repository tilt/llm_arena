"""Experiment configuration (YAML): scenarios × role-bound model configs × tasks × repeats."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator

from llm_arena.core.errors import ConfigError
from llm_arena.decisions.config import DecisionConfig
from llm_arena.runner.presets import ModelPreset
from llm_arena.runner.study import StudyConfig, StudyTag

SandboxConfigMode = Literal["auto", "docker", "unsafe-process", "subprocess"]


def configured_sandbox_mode(explicit: str | None = None) -> SandboxConfigMode:
    """Resolve the CLI override and the one allowed environment source for sandbox selection."""
    value = explicit or os.environ.get("ARENA_SANDBOX", "auto")
    if value not in ("auto", "docker", "unsafe-process", "subprocess"):
        raise ConfigError("ARENA_SANDBOX/--sandbox must be auto, docker or unsafe-process")
    return cast("SandboxConfigMode", value)


def configured_dev_origin() -> str | None:
    value = os.environ.get("ARENA_DEV_ORIGIN")
    if not value:
        return None
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"ARENA_DEV_ORIGIN must be an exact loopback origin: {exc}") from exc
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(
            "ARENA_DEV_ORIGIN must be an exact loopback origin with a port, for example http://localhost:5173"
        )
    return value.removesuffix("/")


class PipelineConfig(BaseModel):
    """One contestant: a name, a role → model binding, and pattern parameters."""

    name: str
    roles: dict[str, str] = Field(default_factory=dict, description="role -> model alias or 'provider:model'")
    params: dict[str, Any] = Field(
        default_factory=dict, description="pattern params, applied to every scenario that knows the key"
    )
    scenario_params: dict[str, dict[str, Any]] = Field(default_factory=dict, description="per-scenario overrides")
    preset: str | None = Field(
        default=None,
        validation_alias=AliasChoices("preset", "baseline"),  # `baseline:` from older experiment files still works
        description="model preset: roles not bound explicitly run on its model for their kind",
    )
    study: StudyTag | None = Field(
        default=None,
        description="marks a configuration that swaps one step's model (or a study's baseline): the report labels its"
        " effect by step and candidate model",
    )
    compare_to: str | None = Field(
        default=None,
        description="another configuration of the experiment, its baseline: the report shows the effect of what this"
        " one changes against it, on the tasks both ran",
    )
    scenario_roles: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="scenario -> role -> model: per-scenario bindings that override `roles`"
    )
    scenarios: list[str] | None = Field(default=None, description="restrict to these scenarios")
    decisions: DecisionConfig | None = Field(
        default=None, description="control policy for scenarios that support one; None: the agent decides"
    )

    @model_validator(mode="after")
    def _preset_or_default(self) -> PipelineConfig:
        # The preset fills every unbound role before "*" would, so a default model next to it never runs.
        if self.preset and self.roles.get("*"):
            raise ValueError(
                f"{self.name}: set either a preset ({self.preset}) or a default model '*' ({self.roles['*']}), not both;"
                " to change single steps on top of a preset, bind those roles"
            )
        return self

    def roles_for(self, scenario: str) -> dict[str, str]:
        return {**self.roles, **self.scenario_roles.get(scenario, {})}

    def params_for(self, scenario: str, known: set[str]) -> dict[str, Any]:
        shared = {key: value for key, value in self.params.items() if key in known}
        return {**shared, **self.scenario_params.get(scenario, {})}


class ArenaConfig(BaseModel):
    enabled: bool = False
    judge: str | None = None  # defaults to the experiment judge
    max_pairs_per_task: int = 10


class ExperimentConfig(BaseModel):
    name: str
    models_file: str = "configs/models.yaml"
    scenarios: list[str] = Field(max_length=30)
    configs: list[PipelineConfig] = Field(default_factory=list, max_length=50)
    study: StudyConfig | None = Field(
        default=None, description="replacement study: baseline + one config per swapped role and candidate model"
    )
    repeats: int = Field(default=1, ge=1, le=100)
    limit: int | None = Field(default=None, ge=1, description="max tasks per scenario")
    task_ids: list[str] | None = None
    split: Literal["all", "dev", "test"] = Field(
        default="all", description="tasks of this split only (tasks without a split are always included)"
    )
    judge: str | None = None
    arena: ArenaConfig = Field(default_factory=ArenaConfig)
    max_parallel_trials: int = Field(default=4, ge=1, le=16)
    max_cost_usd: float | None = Field(
        default=None, ge=0, description="stop admitting calls near this best-effort spend limit"
    )
    budget_mode: Literal["best_effort", "strict"] = "best_effort"
    presets: dict[str, ModelPreset] = Field(
        validation_alias=AliasChoices("presets", "baselines"),
        default_factory=dict,
        description="presets defined in the experiment itself (override the runtime's)",
    )
    trial_timeout_s: float = Field(default=900.0, gt=0, le=3600)
    seed: int = 0

    @model_validator(mode="before")
    @classmethod
    def _single_scenario(cls, data: Any) -> Any:
        if isinstance(data, dict) and "scenario" in data and "scenarios" not in data:
            data = {**data, "scenarios": [data.pop("scenario")]}
        return data

    @model_validator(mode="after")
    def _unique_names(self) -> ExperimentConfig:
        if not self.configs and self.study is None:
            raise ValueError("an experiment needs configs or a study")
        names = [config.name for config in self.configs]
        if len(names) != len(set(names)):
            raise ValueError(f"config names must be unique: {names}")
        for config in self.configs:
            if config.compare_to is not None and (config.compare_to == config.name or config.compare_to not in names):
                raise ValueError(
                    f"{config.name}: compare_to must name another configuration, not {config.compare_to!r}"
                )
        return self


def load_experiment(path: str | Path) -> ExperimentConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return ExperimentConfig.model_validate(raw)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"invalid experiment config {path}: {exc}") from exc

"""Experiment configuration (YAML): scenarios × role-bound model configs × tasks × repeats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from llm_arena.core.errors import ConfigError


class PipelineConfig(BaseModel):
    """One contestant: a name, a role → model binding, and pattern parameters."""

    name: str
    roles: dict[str, str] = Field(description="role -> model alias or 'provider:model'")
    params: dict[str, Any] = Field(
        default_factory=dict, description="pattern params, applied to every scenario that knows the key"
    )
    scenario_params: dict[str, dict[str, Any]] = Field(default_factory=dict, description="per-scenario overrides")
    scenarios: list[str] | None = Field(default=None, description="restrict to these scenarios")

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
    scenarios: list[str]
    configs: list[PipelineConfig]
    repeats: int = Field(default=1, ge=1)
    limit: int | None = Field(default=None, description="max tasks per scenario")
    task_ids: list[str] | None = None
    judge: str | None = None
    arena: ArenaConfig = Field(default_factory=ArenaConfig)
    max_parallel_trials: int = 4
    max_cost_usd: float | None = Field(default=None, description="stop the run once model spend reaches this limit")
    trial_timeout_s: float = 900.0
    seed: int = 0

    @model_validator(mode="before")
    @classmethod
    def _single_scenario(cls, data: Any) -> Any:
        if isinstance(data, dict) and "scenario" in data and "scenarios" not in data:
            data = {**data, "scenarios": [data.pop("scenario")]}
        return data

    @model_validator(mode="after")
    def _unique_names(self) -> ExperimentConfig:
        names = [config.name for config in self.configs]
        if len(names) != len(set(names)):
            raise ValueError(f"config names must be unique: {names}")
        return self


def load_experiment(path: str | Path) -> ExperimentConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return ExperimentConfig.model_validate(raw)
    except (OSError, ValueError) as exc:
        raise ConfigError(f"invalid experiment config {path}: {exc}") from exc

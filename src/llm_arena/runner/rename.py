"""Renaming a finished run: its display name and the names of its setups (configurations).

Only names change. Run and trial ids stay, so links, artifacts and resuming keep working. The
leaderboard pools trials by setup fingerprint, so a rename relabels an entry and never moves trials.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.core.errors import ConfigError
from llm_arena.runner.ports import RunData


class RenameRun(BaseModel):
    name: str | None = Field(default=None, description="new display name of the run (None: unchanged)")
    configs: dict[str, str] = Field(default_factory=dict, description="old setup name -> new setup name")


def config_names(run: dict[str, Any], trials: list[dict[str, Any]]) -> list[str]:
    configs = json.loads(run.get("config_json") or "{}").get("configs", [])
    return sorted({*(str(c["name"]) for c in configs if c.get("name")), *(str(t["config"]) for t in trials)})


def checked_renames(request: RenameRun, current: list[str]) -> dict[str, str]:
    """The renames that change something; ConfigError on an empty, unknown or clashing name."""
    if request.name is not None and not request.name.strip():
        raise ConfigError("the run name cannot be empty")
    renames = {old: new.strip() for old, new in request.configs.items() if new.strip() != old}
    unknown = sorted(set(renames) - set(current))
    if unknown:
        raise ConfigError(f"this run has no setup named {', '.join(unknown)}")
    if not all(renames.values()):
        raise ConfigError("setup names cannot be empty")
    after = [renames.get(name, name) for name in current]
    if len(after) != len(set(after)):
        raise ConfigError("setup names must be unique within a run")
    return renames


def rename_data(data: RunData, request: RenameRun) -> tuple[RunData, dict[str, str]]:
    """The run's rows with the new names, and the setup renames applied (old -> new)."""
    renames = checked_renames(request, config_names(data.run, data.trials))
    name = request.name.strip() if request.name is not None else None

    def swap(value: Any) -> Any:
        return renames.get(value, value)

    config = json.loads(data.run.get("config_json") or "{}")
    if name is not None:
        config["name"] = name
    for entry in config.get("configs", []):
        entry["name"] = swap(entry.get("name"))
        if entry.get("compare_to"):  # a renamed baseline keeps its comparisons
            entry["compare_to"] = swap(entry["compare_to"])
    run = {**data.run, "config_json": json.dumps(config), **({"name": name} if name is not None else {})}
    renamed = RunData(
        run=run,
        trials=[{**t, "config": swap(t["config"])} for t in data.trials],
        scores=data.scores,
        battles=[{**b, "config_a": swap(b["config_a"]), "config_b": swap(b["config_b"])} for b in data.battles],
        decisions=[{**d, "config": swap(d["config"])} for d in data.decisions],
    )
    return renamed, renames


def rename_trace(trace: dict[str, Any] | None, renames: dict[str, str]) -> dict[str, Any] | None:
    """Traces carry their trial record, including the setup name."""
    trial = (trace or {}).get("trial")
    if isinstance(trial, dict) and trial.get("config") in renames:
        trial["config"] = renames[trial["config"]]
    return trace

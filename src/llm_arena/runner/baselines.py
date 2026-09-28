"""Baseline profiles: one model per kind of step (text, vision, code, agent, decision).

A config with `baseline: local-small` runs every role it does not bind explicitly on the profile's
model for that role's kind. Swapping one role on top of a baseline is how the effect of a model on
one step is measured. References carry their call settings (`#reasoning=none`), so profiles work
in every runtime without an alias file.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import yaml
from pydantic import BaseModel, Field

from llm_arena.core.errors import ConfigError
from llm_arena.scenarios.base import RoleKind

KINDS: tuple[RoleKind, ...] = get_args(RoleKind)


class BaselineProfile(BaseModel):
    label: str
    description: str = ""
    models: dict[RoleKind, str] = Field(description="step kind -> model reference")
    decision_service: str | None = Field(
        default=None, description="'ollaya:<model>' or 'jev:<model>': the dedicated decision model, if any"
    )

    def model_for(self, kind: RoleKind) -> str:
        return self.models.get(kind) or self.models.get("text") or next(iter(self.models.values()))


_LOCAL_TEXT = "ollama:qwen3:4b#reasoning=none"
DEFAULT_BASELINES: dict[str, BaselineProfile] = {
    "local-small": BaselineProfile(
        label="Local small",
        description="Qwen3 4B with thinking off for text, code, agents and decisions; Qwen3-VL 8B for images; "
        "winnow (via Ollaya) as the dedicated decision model. Runs on a laptop.",
        models={
            "text": _LOCAL_TEXT,
            "code": _LOCAL_TEXT,
            "agent": _LOCAL_TEXT,
            "decision": _LOCAL_TEXT,
            "vision": "ollama:qwen3-vl:8b#reasoning=none",
        },  # fmt: skip
        decision_service="ollaya:winnow:e4b",
    ),
    "openai-mini": BaselineProfile(
        label="OpenAI mini",
        description="GPT-5 mini with low reasoning effort for every kind of step. Needs an OpenAI key; works in "
        "the browser too.",
        models=dict.fromkeys(KINDS, "openai:gpt-5-mini#reasoning=low"),
    ),
}


def load_baselines(*paths: Path) -> dict[str, BaselineProfile]:
    """The shipped profiles, overridden and extended by YAML files ({profiles: {name: profile}}) that exist."""
    profiles = dict(DEFAULT_BASELINES)
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            profiles |= {name: BaselineProfile.model_validate(p) for name, p in (raw.get("profiles") or {}).items()}
        except (OSError, ValueError) as exc:
            raise ConfigError(f"invalid baseline profiles in {path}: {exc}") from exc
    return profiles


def save_profile(path: Path, name: str, profile: BaselineProfile | None) -> None:
    """Write (or with None remove) one profile in a local override file."""
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    profiles = dict(raw.get("profiles") or {})
    if profile is None:
        profiles.pop(name, None)
    else:
        profiles[name] = profile.model_dump(exclude_none=True)
    path.write_text(yaml.safe_dump({"profiles": profiles}, sort_keys=False, allow_unicode=True), encoding="utf-8")

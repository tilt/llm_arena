"""A unit of work for a scenario: prompt plus the gold data its evaluators need."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Task(BaseModel):
    id: str
    prompt: str
    data: dict[str, Any] = Field(default_factory=dict)  # gold answers, expected state, seeds …
    tags: list[str] = Field(default_factory=list)

"""Human-readable descriptions of a scenario and of each task's ground truth, for scenario pages and docs.

`Brief` says what a scenario tests and how it is graded; `TaskView` shows one task as a person
would read it: the prompt and what counts as a correct outcome. Each scenario renders its own
ground truth (gold SQL and rows, expected mailbox changes, the refund policy says …) instead of
exposing raw task data.
"""

from __future__ import annotations

import json
import textwrap
from typing import Any, Literal

from pydantic import BaseModel, Field

ExpectationFormat = Literal["text", "list", "code", "table", "json"]


class Expectation(BaseModel):
    label: str
    value: Any = Field(description="text, list of strings, code, table rows (list of lists) or JSON")
    format: ExpectationFormat = "text"
    language: str | None = Field(default=None, description="for code: sql, python, …")


class TaskView(BaseModel):
    id: str
    prompt: str
    expected: list[Expectation]
    tags: list[str] = Field(default_factory=list)
    split: str | None = None
    note: str = ""


class Brief(BaseModel):
    summary: str = Field(description="what the scenario tests, in one or two sentences")
    environment: str = Field(description="what the agent works with")
    criteria: dict[str, str] = Field(description="pass criterion -> what it checks, in plain words")
    measured: list[str] = Field(default_factory=list, description="step-level measurements worth knowing")
    traps: list[str] = Field(default_factory=list, description="what makes the tasks hard")
    compare: list[str] = Field(default_factory=list, description="useful ablations (parameters to vary)")


def text(label: str, value: Any) -> Expectation:
    return Expectation(label=label, value=str(value), format="text")


def bullet(label: str, items: list[Any]) -> Expectation:
    return Expectation(label=label, value=[str(item) for item in items], format="list")


def code(label: str, value: str, language: str) -> Expectation:
    first, _, rest = value.strip().partition("\n")
    body = f"{first}\n{textwrap.dedent(rest)}" if rest else first  # continuation lines often carry source indentation
    return Expectation(label=label, value=body, format="code", language=language)


def table(label: str, rows: list[list[Any]]) -> Expectation:
    return Expectation(label=label, value=[[str(cell) for cell in row] for row in rows], format="table")


def as_json(label: str, value: Any) -> Expectation:
    return Expectation(label=label, value=json.loads(json.dumps(value, default=str)), format="json")

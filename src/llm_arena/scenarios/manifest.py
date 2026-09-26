"""Scenario manifests: the language-neutral description the UI (and any other runtime) reads.

Built from the scenario classes (the single source of truth) and exported as JSON with the other
contracts. Wiki links point into the data-science wiki so users can look up each pattern.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

WIKI_BASE = os.getenv("ARENA_WIKI_BASE", "https://tilt.github.io/data-science-wiki/11-generative-ai")

Requirement = Literal["sandbox", "live_network", "local_models"]


class WikiLink(BaseModel):
    title: str
    url: str


def wiki(slug: str, title: str) -> WikiLink:
    return WikiLink(title=title, url=f"{WIKI_BASE}/{slug}")


EVALUATION_LINKS = [
    wiki("agent-evaluation", "Agent evaluation"),
    wiki("evaluation-harnesses", "Evaluation harnesses"),
    wiki("llm-as-judge", "LLM-as-judge"),
]

PATTERN_LINKS: dict[str, list[WikiLink]] = {
    "reflection": [wiki("reflection-and-reviewer-patterns", "Reflection and reviewer patterns")],
    "tool_use": [
        wiki("tool-use-and-function-calling", "Tool use and function calling"),
        wiki("tool-routing", "Tool routing"),
    ],
    "tool_use+reflection": [
        wiki("tool-use-and-function-calling", "Tool use and function calling"),
        wiki("reflection-and-reviewer-patterns", "Reflection and reviewer patterns"),
    ],
    "react": [wiki("agent-loops#react-reason-act-observe", "ReAct: reason, act, observe")],
    "code_execution": [wiki("agent-loops#code-as-an-action", "Code as an action")],
    "code_execution+reflection": [
        wiki("agent-loops#code-as-an-action", "Code as an action"),
        wiki("reflection-and-reviewer-patterns", "Reflection and reviewer patterns"),
    ],
    "planning": [wiki("planning", "Planning")],
    "multi_agent": [wiki("multi-agent-systems", "Multi-agent systems")],
    "benchmark": [wiki("evaluation-harnesses", "Evaluation harnesses")],
}


class RoleManifest(BaseModel):
    name: str
    description: str
    needs: list[str] = Field(default_factory=list, description="capabilities the bound model must have")
    fallback: str | None = Field(default=None, description="optional role: reuses this role's model when unbound")


class ParamManifest(BaseModel):
    name: str
    type: Literal["integer", "number", "boolean", "string"]
    default: Any
    choices: list[Any] | None = None
    description: str = ""


class ScenarioManifest(BaseModel):
    id: str
    title: str
    pattern: str
    description: str
    kind: Literal["pattern", "benchmark"]
    roles: list[RoleManifest]
    params: list[ParamManifest]
    pass_criteria: list[str]
    requires: list[Requirement] = Field(default_factory=list)
    open_ended: bool = False
    tasks: int
    wiki: list[WikiLink] = Field(default_factory=list)


def param_type(value: Any) -> Literal["integer", "number", "boolean", "string"]:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"

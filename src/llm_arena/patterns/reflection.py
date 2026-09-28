"""Reflection: draft → critique → revise, for N rounds or until the critic accepts.

The critic can be the same model, a different model, or be grounded in external feedback
(execution results, test output, a rendered chart) — the scenario decides by what it passes
into `critique`. Every critique is traced so reviewer precision/recall can be scored per step.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient, structured
from llm_arena.llm.types import Message


class Critique(BaseModel):
    verdict: Literal["accept", "revise"] = Field(description="accept if no change is needed")
    issues: list[str] = Field(default_factory=list, description="Concrete, actionable problems; empty if none")
    summary: str = ""


@dataclass
class ReflectionResult:
    drafts: list[str] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)

    @property
    def final(self) -> str:
        return self.drafts[-1]

    @property
    def initial(self) -> str:
        return self.drafts[0]


DraftFn = Callable[[], Awaitable[str]]
CritiqueFn = Callable[[str, int], Awaitable[Critique]]
ReviseFn = Callable[[str, Critique, int], Awaitable[str]]


async def reflect(
    *, draft: DraftFn, critique: CritiqueFn, revise: ReviseFn, rounds: int, trace: Trace
) -> ReflectionResult:
    result = ReflectionResult()
    with trace.in_step("draft"), trace.span("step", "draft", attrs={"round": 0}) as span:
        result.drafts.append(await draft())
        span.output = result.drafts[-1]
    for round_index in range(1, rounds + 1):
        with trace.in_step("critique"), trace.span("critique", "critique", attrs={"round": round_index}) as span:
            review = await critique(result.final, round_index)
            span.output = review.model_dump()
            span.attrs.update({"verdict": review.verdict, "n_issues": len(review.issues)})
        result.critiques.append(review)
        if review.verdict == "accept":
            break
        with trace.in_step("revise"), trace.span("step", "revise", attrs={"round": round_index}) as span:
            result.drafts.append(await revise(result.final, review, round_index))
            span.output = result.drafts[-1]
    return result


async def llm_critique(critic: LLMClient, messages: list[Message]) -> Critique:
    """Structured critique from a model; the scenario builds the messages (rubric, feedback)."""
    review, _ = await structured(critic, messages, Critique)
    return review

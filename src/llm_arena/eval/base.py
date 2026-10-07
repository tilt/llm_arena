"""Evaluator protocol and the data it sees: task, final output, environment state, trace.

Step-level evaluators read spans from the trace; end-to-end evaluators read the final output
and the final state of the mock environment. Both return `Score`s tagged with their level.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from llm_arena.core.task import Task
from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient
from llm_arena.sandbox.base import Sandbox

Level = Literal["step", "e2e"]

__all__ = ["EvalContext", "Evaluator", "FunctionEvaluator", "Level", "Score", "Task", "TrialOutput", "evaluate_all"]


class Score(BaseModel):
    name: str
    value: float
    level: Level
    passed: bool | None = None
    rationale: str = ""


@dataclass
class TrialOutput:
    final: str
    env_state: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)  # e.g. rendered chart PNGs
    extras: dict[str, Any] = field(default_factory=dict)  # pattern-specific: drafts, plans, …


@dataclass
class EvalContext:
    task: Task
    output: TrialOutput
    trace: Trace
    judge: LLMClient | None = None
    params: dict[str, Any] = field(default_factory=dict)
    sandbox: Sandbox | None = None  # for graders that run code (HumanEval/MBPP tests)


class Evaluator(Protocol):
    @property
    def name(self) -> str: ...

    async def evaluate(self, ctx: EvalContext) -> list[Score]: ...


async def evaluate_all(evaluators: list[Evaluator], ctx: EvalContext) -> list[Score]:
    """Every evaluator's scores; a broken evaluator becomes an error score instead of losing the trial."""
    scores: list[Score] = []
    for evaluator in evaluators:
        try:
            scores += await evaluator.evaluate(ctx)
        except Exception as exc:
            scores.append(Score(name=f"{evaluator.name}.error", value=0.0, level="e2e", rationale=f"{exc}"[:500]))
    return scores


ScoreFn = Callable[[EvalContext], "list[Score] | Score | None | Awaitable[list[Score] | Score | None]"]


class FunctionEvaluator:
    """Wrap a plain (sync or async) function as an Evaluator. Returning None means 'not applicable'."""

    def __init__(self, name: str, fn: ScoreFn) -> None:
        self.name = name
        self._fn = fn

    async def evaluate(self, ctx: EvalContext) -> list[Score]:
        result = self._fn(ctx)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return []
        return [result] if isinstance(result, Score) else list(result)


def evaluator(name: str) -> Callable[[ScoreFn], FunctionEvaluator]:
    def wrap(fn: ScoreFn) -> FunctionEvaluator:
        return FunctionEvaluator(name, fn)

    return wrap


def ratio_score(
    name: str,
    numerator: float,
    denominator: float,
    level: Level,
    *,
    threshold: float | None = None,
    empty: float = 1.0,
    rationale: str = "",
) -> Score:
    """A rate in [0, 1]; `empty` is the value when there is nothing to count (e.g. no tool calls)."""
    value = numerator / denominator if denominator else empty
    passed = None if threshold is None else value >= threshold
    detail = rationale or f"{numerator:g}/{denominator:g}"
    return Score(name=name, value=value, level=level, passed=passed, rationale=detail)

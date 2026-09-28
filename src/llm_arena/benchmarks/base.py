"""Shared shape of single-model benchmarks: one `model` role, one completion per task, a grader."""

from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, ClassVar

from llm_arena.benchmarks.hf import HFSource
from llm_arena.eval.base import EvalContext, Evaluator, FunctionEvaluator, Score, Task, TrialOutput
from llm_arena.llm.client import user
from llm_arena.patterns.roles import RoleModels
from llm_arena.scenarios.base import RoleRequirement, RunContext, Scenario
from llm_arena.scenarios.brief import Brief, Expectation, TaskView, as_json

_ANSWER_LINE = re.compile(r"answer\s*(?:is)?\s*[:：]\s*(.+)", re.IGNORECASE)


def answer_line(text: str) -> str | None:
    """The content after the last 'Answer:' marker, if any."""
    matches = _ANSWER_LINE.findall(text)
    return matches[-1].strip() if matches else None


class Benchmark(Scenario):
    pattern = "benchmark"
    kind = "benchmark"
    roles = [RoleRequirement("model", "the model under test")]
    default_params = {"max_tokens": None}
    pass_criteria = ["correct"]
    sample_size: ClassVar[int] = 100
    # Pinned upstream files; runtimes whose loader cannot fetch synchronously prefetch these first.
    sources: ClassVar[tuple[HFSource, ...]] = ()

    # What the grader checks, in plain words (subclasses refine it).
    grading: ClassVar[str] = "the answer matches the reference"

    def task_count(self) -> int:
        return self.sample_size  # without downloading the dataset

    def brief(self) -> Brief:
        return Brief(
            summary=self.description,
            environment=f"One model call per task, no tools; a deterministic sample of {self.sample_size} items "
            "(seed 0) from the pinned public dataset.",
            criteria={"correct": self.grading},
            compare=["the same model with thinking on and off", "a small model vs a large one"],
        )

    def expected(self, task: Task) -> list[Expectation]:
        return [as_json("Reference", task.data)]

    def describe(self, task: Task) -> TaskView:
        return TaskView(id=task.id, prompt=task.prompt, tags=task.tags, expected=self.expected(task))

    async def run(self, task: Task, models: RoleModels, ctx: RunContext) -> TrialOutput:
        with ctx.trace.in_step("answer"):
            response = await models["model"].complete([user(task.prompt)], max_tokens=ctx.params["max_tokens"])
        return TrialOutput(final=response.content)

    def evaluators(self, params: dict[str, Any]) -> list[Evaluator]:
        return [FunctionEvaluator(f"{self.name}_grader", self._grade)]

    async def _grade(self, ctx: EvalContext) -> list[Score]:
        return await self.grade(ctx)

    @abstractmethod
    async def grade(self, ctx: EvalContext) -> list[Score]: ...


def correct_score(correct: bool, rationale: str = "") -> Score:
    return Score(name="correct", value=float(correct), level="e2e", passed=correct, rationale=rationale)

"""HumanEval and MBPP subsets: generated code runs against the reference tests in the sandbox (pass@1)."""

from __future__ import annotations

from typing import ClassVar

from llm_arena.benchmarks.base import Benchmark, correct_score
from llm_arena.benchmarks.hf import HUMANEVAL, MBPP, load_rows, stratified_sample
from llm_arena.eval.base import EvalContext, Score, Task
from llm_arena.patterns.codeact import extract_code
from llm_arena.sandbox.base import Sandbox
from llm_arena.scenarios.base import register
from llm_arena.scenarios.brief import Expectation, code, text


async def run_tests(sandbox: Sandbox | None, program: str, timeout_s: float = 15.0) -> tuple[bool, str]:
    if sandbox is None:
        raise RuntimeError("code benchmarks need a sandbox to run the reference tests")
    result = await sandbox.run(program, timeout_s=timeout_s)
    return result.ok, result.observation()[-600:]


@register
class HumanEvalBench(Benchmark):
    name = "humaneval"
    sources = (HUMANEVAL,)
    title = "HumanEval (code)"
    tokens_per_trial = 1200
    requires = frozenset({"sandbox"})
    description = "HumanEval subset (MIT): complete a Python function; graded by the reference unit tests."
    sample_size = 60

    grading: ClassVar[str] = "the completed function passes the reference unit tests"

    def expected(self, task: Task) -> list[Expectation]:
        return [code("Reference tests", task.data["test"], "python"), text("Function", task.data["entry_point"])]

    def load_tasks(self) -> list[Task]:
        rows = stratified_sample(load_rows(HUMANEVAL), self.sample_size, seed=0)
        return [
            Task(
                id=row["task_id"].replace("/", "-").lower(),
                prompt="Complete this Python function. Return the complete function (with imports) in one "
                f"```python block.\n\n```python\n{row['prompt']}```",
                data={"prompt": row["prompt"], "test": row["test"], "entry_point": row["entry_point"]},
            )
            for row in rows
        ]

    async def grade(self, ctx: EvalContext) -> list[Score]:
        code = extract_code(ctx.output.final) or ctx.output.final
        if f"def {ctx.task.data['entry_point']}" not in code:
            code = ctx.task.data["prompt"] + code  # model returned only the body
        program = f"{code}\n\n{ctx.task.data['test']}\n\ncheck({ctx.task.data['entry_point']})\n"
        ok, detail = await run_tests(ctx.sandbox, program)
        return [correct_score(ok, "" if ok else detail)]


@register
class MBPPBench(Benchmark):
    name = "mbpp"
    sources = (MBPP,)
    title = "MBPP (code)"
    tokens_per_trial = 900
    requires = frozenset({"sandbox"})
    description = "MBPP sanitized test subset (CC-BY-4.0): write a function from a description and one example test."
    sample_size = 60

    grading: ClassVar[str] = "the function passes the reference tests"

    def expected(self, task: Task) -> list[Expectation]:
        return [code("Reference tests", "\n".join(task.data["tests"]), "python")]

    def load_tasks(self) -> list[Task]:
        rows = stratified_sample(load_rows(MBPP), self.sample_size, seed=0)
        return [
            Task(
                id=f"mbpp-{row['task_id']}",
                prompt=f"{row['prompt']}\nYour code should pass this test:\n{row['test_list'][0]}\n\n"
                "Return the solution in one ```python block.",
                data={"tests": list(row["test_list"]), "imports": list(row.get("test_imports") or [])},
            )
            for row in rows
        ]

    async def grade(self, ctx: EvalContext) -> list[Score]:
        code = extract_code(ctx.output.final) or ctx.output.final
        program = "\n".join([*ctx.task.data["imports"], code, *ctx.task.data["tests"]])
        ok, detail = await run_tests(ctx.sandbox, program)
        return [correct_score(ok, "" if ok else detail)]

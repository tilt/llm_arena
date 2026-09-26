"""Benchmark graders on hand-written fixture items (no dataset download needed)."""

from __future__ import annotations

from llm_arena.adapters.server.subprocess_sandbox import SubprocessSandbox
from llm_arena.benchmarks.code import HumanEvalBench, MBPPBench
from llm_arena.benchmarks.function_calling import FunctionCallingBench
from llm_arena.benchmarks.ifeval import CHECKERS, IFEvalBench
from llm_arena.benchmarks.knowledge import GSM8KBench, MMLUProBench, parse_choice
from llm_arena.core.trace import Trace
from llm_arena.eval.base import EvalContext, Task, TrialOutput


def _ctx(task: Task, final: str, **extras: object) -> EvalContext:
    return EvalContext(task, TrialOutput(final=final, extras=dict(extras)), Trace(), sandbox=SubprocessSandbox())


async def test_gsm8k_uses_answer_line() -> None:
    task = Task(id="g", prompt="", data={"answer": 18.0})
    assert (await GSM8KBench().grade(_ctx(task, "3 + 15 = 18 eggs\nAnswer: 18")))[0].passed
    assert not (await GSM8KBench().grade(_ctx(task, "Answer: 19. Checking: 18 would be wrong")))[0].passed


async def test_mmlu_pro_choice_parsing() -> None:
    assert parse_choice("... so it's C.\nAnswer: (C)") == "C"
    assert parse_choice("the answer is (J)") == "J"
    task = Task(id="m", prompt="", data={"answer": "B"})
    assert (await MMLUProBench().grade(_ctx(task, "Answer: B")))[0].passed


async def test_humaneval_runs_reference_tests() -> None:
    prompt = 'def add(a, b):\n    """Add."""\n'
    task = Task(
        id="h",
        prompt="",
        data={"prompt": prompt, "entry_point": "add", "test": "def check(f):\n    assert f(2, 3) == 5\n"},
    )
    assert (await HumanEvalBench().grade(_ctx(task, "```python\ndef add(a, b):\n    return a + b\n```")))[0].passed
    assert (await HumanEvalBench().grade(_ctx(task, "    return a + b\n")))[0].passed  # body only
    assert not (await HumanEvalBench().grade(_ctx(task, "```python\ndef add(a, b):\n    return a - b\n```")))[0].passed


async def test_mbpp_runs_asserts() -> None:
    task = Task(id="m", prompt="", data={"tests": ["assert double(2) == 4"], "imports": []})
    assert (await MBPPBench().grade(_ctx(task, "```python\ndef double(x):\n    return 2 * x\n```")))[0].passed


async def test_ifeval_checkers() -> None:
    assert CHECKERS["punctuation:no_comma"]("no commas here", {})
    assert CHECKERS["length_constraints:number_words"]("one two three", {"relation": "less than", "num_words": 4})
    assert CHECKERS["detectable_format:number_bullet_lists"]("* a\n* b", {"num_bullets": 2})
    assert CHECKERS["detectable_format:title"]("<<My Title>>\ntext", {})
    assert not CHECKERS["change_case:english_lowercase"]("Mixed", {})
    task = Task(
        id="i",
        prompt="",
        data={"instructions": ["punctuation:no_comma", "keywords:existence"], "kwargs": [{}, {"keywords": ["arena"]}]},
    )
    scores = await IFEvalBench().grade(_ctx(task, "the arena, obviously"))
    assert not scores[0].passed and scores[1].value == 0.5


async def test_function_calling_ast_match() -> None:
    bench = FunctionCallingBench()
    task = next(t for t in bench.load_tasks() if t.id == "parallel_weather")
    right = [
        {"name": "get_weather", "args": {"city": "quistra"}},
        {"name": "get_weather", "args": {"city": "Varrel", "unit": "celsius"}},
    ]
    assert (await bench.grade(_ctx(task, "", calls=right)))[0].passed
    extra = [*right, {"name": "set_timer", "args": {"minutes": 1}}]
    assert not (await bench.grade(_ctx(task, "", calls=extra)))[0].passed
    irrelevant = next(t for t in bench.load_tasks() if t.id == "irrelevant_math")
    assert (await bench.grade(_ctx(irrelevant, "391", calls=[])))[0].passed

"""Every scenario explains itself and renders each task's ground truth readably (no raw data dumps)."""

from __future__ import annotations

import pytest

import llm_arena.benchmarks  # noqa: F401
import llm_arena.scenarios.catalog  # noqa: F401
from llm_arena.benchmarks.base import Benchmark
from llm_arena.eval.base import Task
from llm_arena.scenarios.base import SCENARIOS, get_scenario

PATTERNS = sorted(name for name in SCENARIOS if get_scenario(name).kind == "pattern")
BENCHMARK_SAMPLES = {
    "gsm8k": {"answer": 72.0},
    "mmlu_pro": {"answer": "C"},
    "humaneval": {"prompt": "def f(x):", "test": "def check(f):\n    assert f(1) == 2", "entry_point": "f"},
    "mbpp": {"tests": ["assert f(1) == 2"], "imports": []},
    "ifeval": {
        "instructions": ["length_constraints:number_words"],
        "kwargs": [{"relation": "less than", "num_words": 50}],
    },
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_has_a_brief_covering_its_pass_criteria(name: str) -> None:
    scenario = get_scenario(name)
    brief = scenario.brief()
    assert brief is not None and brief.summary and brief.environment
    assert set(brief.criteria) == set(scenario.pass_criteria), name
    assert scenario.manifest().brief == brief


@pytest.mark.parametrize("name", PATTERNS)
def test_every_task_describes_its_expected_outcome(name: str) -> None:
    scenario = get_scenario(name)
    for task in scenario.load_tasks():
        view = scenario.describe(task)
        assert view.id == task.id and view.prompt == task.prompt
        assert view.expected, (name, task.id)
        assert all(e.format != "json" or e.label != "Ground truth (raw)" for e in view.expected), (name, task.id)
        assert all(e.value not in ("", [], None) for e in view.expected), (name, task.id)


def test_benchmarks_render_their_references() -> None:
    for name, data in BENCHMARK_SAMPLES.items():
        scenario = get_scenario(name)
        assert isinstance(scenario, Benchmark)
        expected = scenario.expected(Task(id="t", prompt="p", data=data))
        assert expected and expected[0].label != "Reference", name
    calls = get_scenario("function_calling")
    view = calls.describe(calls.load_tasks()[0])
    assert view.expected[0].label == "Expected calls"


def test_support_desk_tasks_show_the_policy_facts_and_split() -> None:
    scenario = get_scenario("support_desk")
    view = scenario.describe(next(t for t in scenario.load_tasks() if t.id == "damaged_2006"))
    assert view.split in {"dev", "test"}
    assert view.expected[0].value[0] == "no refund and no cancellation"
    assert "31 days ago" in view.expected[1].value[0]

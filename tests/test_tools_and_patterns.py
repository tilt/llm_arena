from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from llm_arena.core.trace import Trace
from llm_arena.llm.testing import ScriptedLLM, tool_call
from llm_arena.llm.types import ToolCall
from llm_arena.patterns.multi_agent import Worker, orchestrate
from llm_arena.patterns.planning import Plan, PlanStep, basic_validator, plan_and_execute
from llm_arena.patterns.react import parse_react_reply, run_react
from llm_arena.patterns.reflection import Critique, reflect
from llm_arena.patterns.roles import RoleModels
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.registry import ToolRegistry, tool


@tool
def add(a: int, b: Annotated[int, Field(description="second summand")]) -> int:
    """Add two integers."""
    return a + b


@tool(permission="destructive")
def wipe() -> str:
    """Delete everything."""
    return "wiped"


@tool
def explode() -> str:
    """Always fails."""
    raise RuntimeError("boom")


def test_tool_schema_from_signature() -> None:
    schema = add.schema()["function"]
    assert schema["name"] == "add" and schema["description"] == "Add two integers."
    assert schema["parameters"]["required"] == ["a", "b"]
    assert schema["parameters"]["properties"]["b"]["description"] == "second summand"


async def test_executor_classifies_failures_for_step_metrics() -> None:
    trace = Trace()
    executor = ToolExecutor(ToolRegistry([add, wipe, explode]), trace, allowed_permissions=frozenset({"read"}))
    assert (await executor.execute(ToolCall("add", {"a": 1, "b": 2}))).content == "3"
    kinds = [
        (await executor.execute(call)).error_kind
        for call in (
            ToolCall("nope", {}),
            ToolCall("add", {"a": "x", "b": 1}),
            ToolCall("add", {"a": 1, "b": 2, "c": 3}),
            ToolCall("wipe", {}),
            ToolCall("explode", {}),
        )
    ]
    assert kinds == ["unknown_tool", "invalid_args", "invalid_args", "forbidden", "runtime"]
    assert [span.attrs["ok"] for span in trace.select("tool_call")] == [True, False, False, False, False, False]


async def test_tool_loop_stops_on_final_and_on_max_turns() -> None:
    trace = Trace()
    executor = ToolExecutor(ToolRegistry([add]), trace)
    result = await run_tool_loop(ScriptedLLM([tool_call("add", a=2, b=3), "5"]), [], executor)
    assert (result.final, result.stop_reason, result.turns) == ("5", "final", 2)
    looping = ScriptedLLM([tool_call("add", a=1, b=1)] * 3 + ["gave up"])
    result = await run_tool_loop(looping, [], executor, max_turns=3)
    assert result.stop_reason == "max_turns" and result.final == "gave up"


def test_react_parser() -> None:
    assert parse_react_reply("Thought: x\nFinal Answer: Selm") == ("Selm", None)
    final, action = parse_react_reply('Thought: look\nAction: read_article\nAction Input: {"title": "Ostreva"}')
    assert final is None and action is not None and action.args == {"title": "Ostreva"}
    _, bracket = parse_react_reply("Action: search_articles[river]")
    assert bracket is not None and bracket.args == {"query": "river"}
    # An action followed by a hallucinated observation and answer: the action wins.
    _, first = parse_react_reply('Action: add\nAction Input: {"a": 1, "b": 1}\nObservation: 2\nFinal Answer: 2')
    assert first is not None and first.name == "add"


async def test_react_counts_invalid_actions() -> None:
    trace = Trace()
    llm = ScriptedLLM(
        ["I am not following the format", 'Action: add\nAction Input: {"a": 2, "b": 2}', "Final Answer: 4"]
    )
    result = await run_react(llm, "2+2?", ToolExecutor(ToolRegistry([add]), trace), trace)
    assert (result.final, result.invalid_actions, result.steps) == ("4", 1, 3)


async def test_reflection_stops_when_critic_accepts() -> None:
    trace = Trace()
    critiques = iter([Critique(verdict="revise", issues=["too long"]), Critique(verdict="accept")])

    async def draft() -> str:
        return "v0"

    async def critique(text: str, round_index: int) -> Critique:
        return next(critiques)

    async def revise(text: str, review: Critique, round_index: int) -> str:
        return f"v{round_index}"

    result = await reflect(draft=draft, critique=critique, revise=revise, rounds=3, trace=trace)
    assert result.drafts == ["v0", "v1"] and len(result.critiques) == 2
    assert [span.attrs["verdict"] for span in trace.select("critique")] == ["revise", "accept"]


async def test_planning_repairs_invalid_plan_and_replans_after_failed_step() -> None:
    trace = Trace()
    bad_plan = Plan(steps=[PlanStep(id=1, goal="teleport", tools=["teleport"])]).model_dump_json()
    good_plan = Plan(steps=[PlanStep(id=1, goal="add", tools=["add"]), PlanStep(id=2, goal="report")]).model_dump_json()
    replan = Plan(steps=[PlanStep(id=3, goal="add again", tools=["add"])]).model_dump_json()
    planner = ScriptedLLM([bad_plan, good_plan, replan, "final summary"])
    executor_llm = ScriptedLLM([tool_call("add", a=1, b=2), "STEP_FAILED: result looked wrong", "3"])
    result = await plan_and_execute(
        planner,
        executor_llm,
        "add numbers",
        ToolExecutor(ToolRegistry([add]), trace),
        trace,
        validator=basic_validator({"add"}),
    )
    assert result.repairs == 1 and result.replans == 1 and not result.aborted
    assert [r.failed for r in result.records] == [True, False] and result.final == "final summary"


class Numbers(BaseModel):
    values: list[int]


async def test_multi_agent_records_rejected_handoffs() -> None:
    trace = Trace()
    good = Worker("counter", "counts", "Count.", Numbers, ScriptedLLM(['{"values": [1, 2]}']))
    bad = Worker("broken", "breaks", "Break.", Numbers, ScriptedLLM(["no json"]))
    orchestrator = ScriptedLLM(
        [
            '{"assignments": [{"worker": "counter", "instruction": "go"}, '
            '{"worker": "broken", "instruction": "go"}, {"worker": "ghost", "instruction": "go"}]}',
            "composed",
        ]
    )
    result = await orchestrate(orchestrator, [good, bad], "task", trace, compose_instructions="Compose.")
    assert result.blackboard == {"counter": {"values": [1, 2]}}
    assert result.rejected_handoffs == ["broken", "unknown worker 'ghost'"]
    assert [span.attrs["accepted"] for span in trace.select("handoff")] == [True, False]


async def test_role_models_trace_llm_calls_with_role() -> None:
    trace = Trace()
    roles = RoleModels({"generator": ScriptedLLM(["hi"])}, trace)
    await roles.get("critic", "generator").complete([{"role": "user", "content": "x"}])
    span = trace.select("llm_call")[0]
    assert span.role == "critic" and span.output == "hi"

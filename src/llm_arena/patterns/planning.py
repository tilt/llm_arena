"""Plan-and-execute with an explicit plan state, a validator, and replanning on step failure.

Planner and executor are separate roles, so a strong planner with a small executor (or the
reverse) is one config line. Step metrics follow the wiki's planning page: validator rejections,
repairs per plan, and whether replanning was triggered when a step failed.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient, structured
from llm_arena.llm.errors import StructuredOutputError
from llm_arena.llm.types import Message
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.tools.executor import ToolExecutor
from llm_arena.tools.tool_docs import describe_tools

STEP_FAILED = "STEP_FAILED"


class PlanStep(BaseModel):
    id: int
    goal: str = Field(description="What this step must achieve, specific enough to execute")
    tools: list[str] = Field(default_factory=list, description="Tools this step is expected to use")


class Plan(BaseModel):
    rationale: str = ""
    steps: list[PlanStep]


PlanValidator = Callable[[Plan], list[str]]


@dataclass
class StepRecord:
    step: PlanStep
    output: str
    failed: bool


@dataclass
class PlanningResult:
    final: str
    plans: list[Plan] = field(default_factory=list)
    records: list[StepRecord] = field(default_factory=list)
    repairs: int = 0
    replans: int = 0
    aborted: bool = False


def basic_validator(allowed_tools: set[str], max_steps: int = 10) -> PlanValidator:
    def validate(plan: Plan) -> list[str]:
        errors = []
        if not plan.steps:
            errors.append("the plan has no steps")
        if len(plan.steps) > max_steps:
            errors.append(f"the plan has {len(plan.steps)} steps; the maximum is {max_steps}")
        for step in plan.steps:
            unknown = set(step.tools) - allowed_tools
            if unknown:
                errors.append(f"step {step.id} uses unknown tools {sorted(unknown)}")
        return errors

    return validate


async def plan_and_execute(
    planner: LLMClient,
    executor_llm: LLMClient,
    task: str,
    tool_executor: ToolExecutor,
    trace: Trace,
    *,
    validator: PlanValidator,
    context: str = "",
    max_repairs: int = 2,
    max_replans: int = 2,
    max_step_turns: int = 6,
) -> PlanningResult:
    result = PlanningResult(final="")
    tools_doc = describe_tools(tool_executor.registry)
    plan = await _make_plan(planner, task, context, tools_doc, [], validator, max_repairs, trace, result)
    if plan is None:
        result.aborted = True
        return result

    queue = list(plan.steps)
    while queue:
        step = queue.pop(0)
        record = await _execute_step(
            executor_llm, task, context, step, result.records, tool_executor, trace, max_step_turns
        )
        result.records.append(record)
        if record.failed:
            if result.replans >= max_replans:
                result.aborted = True
                break
            result.replans += 1
            new_plan = await _make_plan(
                planner, task, context, tools_doc, result.records, validator, max_repairs, trace, result
            )
            if new_plan is None:
                result.aborted = True
                break
            queue = list(new_plan.steps)

    result.final = await _synthesise(planner, task, context, result.records, trace)
    return result


async def _make_plan(
    planner: LLMClient,
    task: str,
    context: str,
    tools_doc: str,
    done: list[StepRecord],
    validator: PlanValidator,
    max_repairs: int,
    trace: Trace,
    result: PlanningResult,
) -> Plan | None:
    progress = _progress(done)
    messages: list[Message] = [
        {
            "role": "system",
            "content": "You are a planner. Break the task into a short sequence of executable steps. "
            "Each step is carried out by an assistant that can use these tools:\n" + tools_doc,
        },
        {
            "role": "user",
            "content": f"Task: {task}\n{context}\n"
            + (f"\nProgress so far (plan only the REMAINING steps):\n{progress}" if done else ""),
        },
    ]
    for attempt in range(max_repairs + 1):
        with trace.span("plan", "replan" if done else "plan", attrs={"attempt": attempt}) as span:
            try:
                plan, _ = await structured(planner, messages, Plan)
            except StructuredOutputError as exc:
                span.error = str(exc)
                return None
            errors = validator(plan)
            span.output = plan.model_dump()
            span.attrs.update({"valid": not errors, "validation_errors": errors, "n_steps": len(plan.steps)})
        if not errors:
            result.plans.append(plan)
            return plan
        result.repairs += 1
        messages = [
            *messages,
            {"role": "assistant", "content": plan.model_dump_json()},
            {
                "role": "user",
                "content": "The plan is invalid:\n- " + "\n- ".join(errors) + "\nReturn a corrected plan.",
            },
        ]
    return None


async def _execute_step(
    llm: LLMClient,
    task: str,
    context: str,
    step: PlanStep,
    done: list[StepRecord],
    tool_executor: ToolExecutor,
    trace: Trace,
    max_turns: int,
) -> StepRecord:
    messages: list[Message] = [
        {
            "role": "system",
            "content": "You execute one step of a larger plan using the tools. Report the concrete result "
            f"(ids, prices, dates). If the step cannot be achieved, reply with '{STEP_FAILED}: <reason>'.",
        },
        {
            "role": "user",
            "content": f"Overall task: {task}\n{context}\nCompleted steps:\n{_progress(done) or '(none)'}\n\n"
            f"Your step ({step.id}): {step.goal}",
        },
    ]
    with trace.span("step", f"plan_step_{step.id}", input=step.goal) as span:
        loop = await run_tool_loop(llm, messages, tool_executor, max_turns=max_turns)
        failed = STEP_FAILED in loop.final or loop.stop_reason == "max_turns"
        span.output = loop.final
        span.attrs.update({"failed": failed, "stop_reason": loop.stop_reason, "turns": loop.turns})
    return StepRecord(step, loop.final, failed)


async def _synthesise(planner: LLMClient, task: str, context: str, records: list[StepRecord], trace: Trace) -> str:
    with trace.span("step", "synthesis") as span:
        response = await planner.complete(
            [
                {
                    "role": "system",
                    "content": "Write the final answer to the task from the executed steps. Be concrete.",
                },
                {"role": "user", "content": f"Task: {task}\n{context}\nExecuted steps:\n{_progress(records)}"},
            ]
        )
        span.output = response.content
    return response.content


def _progress(records: list[StepRecord]) -> str:
    return "\n".join(
        f"- step {record.step.id} ({'FAILED' if record.failed else 'ok'}): {record.step.goal}\n  result: {record.output}"
        for record in records
    )


def plan_as_json(plan: Plan) -> str:
    return json.dumps(plan.model_dump(), indent=2)

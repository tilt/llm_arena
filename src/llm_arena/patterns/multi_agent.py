"""Orchestrator–workers with typed handoffs ("protocol over personas").

Each worker returns a pydantic object; a handoff that fails validation is *rejected* and
recorded, not silently passed on. Worker outputs land on a shared blackboard that later workers
and the final composer read. The handoff rejection rate is a step-level metric.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient, structured
from llm_arena.llm.errors import StructuredOutputError
from llm_arena.llm.types import Message
from llm_arena.patterns.tool_loop import run_tool_loop
from llm_arena.tools.executor import ToolExecutor


@dataclass
class Worker:
    name: str
    description: str
    instructions: str
    output_model: type[BaseModel]
    llm: LLMClient
    executor: ToolExecutor | None = None  # workers without tools answer from the blackboard alone
    max_turns: int = 6
    step: str | None = None  # workflow step id (defaults to the worker name)


class Assignment(BaseModel):
    worker: str
    instruction: str = Field(description="What this worker must produce, referencing earlier results if needed")


class Delegation(BaseModel):
    assignments: list[Assignment]


@dataclass
class MultiAgentResult:
    final: str
    delegation: Delegation | None
    blackboard: dict[str, Any] = field(default_factory=dict)
    rejected_handoffs: list[str] = field(default_factory=list)


async def orchestrate(
    orchestrator: LLMClient,
    workers: list[Worker],
    task: str,
    trace: Trace,
    *,
    compose_instructions: str,
    fixed_order: list[str] | None = None,
) -> MultiAgentResult:
    """Delegate (or follow `fixed_order`), run workers in sequence, then compose the deliverable."""
    by_name = {worker.name: worker for worker in workers}
    delegation = await _delegate(orchestrator, workers, task, trace, fixed_order)
    result = MultiAgentResult(final="", delegation=delegation)

    for assignment in delegation.assignments:
        worker = by_name.get(assignment.worker)
        if worker is None:
            result.rejected_handoffs.append(f"unknown worker {assignment.worker!r}")
            continue
        output = await _run_worker(worker, task, assignment.instruction, result.blackboard, trace)
        if output is None:
            result.rejected_handoffs.append(worker.name)
        else:
            result.blackboard[worker.name] = output.model_dump()

    with trace.in_step("compose"), trace.span("step", "compose", role="orchestrator") as span:
        response = await orchestrator.complete(
            [
                {"role": "system", "content": compose_instructions},
                {"role": "user", "content": f"Task: {task}\n\nTeam results:\n{_board(result.blackboard)}"},
            ]
        )
        span.output = response.content
    result.final = response.content
    return result


async def _delegate(
    orchestrator: LLMClient, workers: list[Worker], task: str, trace: Trace, fixed_order: list[str] | None
) -> Delegation:
    if fixed_order is not None:
        return Delegation(assignments=[Assignment(worker=name, instruction=task) for name in fixed_order])
    roster = "\n".join(f"- {worker.name}: {worker.description}" for worker in workers)
    messages: list[Message] = [
        {
            "role": "system",
            "content": "You coordinate a team. Assign work to team members in the order it should happen. "
            f"Use each member at most once and only when needed.\nTeam:\n{roster}",
        },
        {"role": "user", "content": task},
    ]
    with trace.in_step("delegate"), trace.span("plan", "delegate", role="orchestrator") as span:
        delegation, _ = await structured(orchestrator, messages, Delegation)
        span.output = delegation.model_dump()
    return delegation


async def _run_worker(
    worker: Worker, task: str, instruction: str, blackboard: dict[str, Any], trace: Trace
) -> BaseModel | None:
    messages: list[Message] = [
        {"role": "system", "content": worker.instructions},
        {
            "role": "user",
            "content": f"Overall task: {task}\nYour assignment: {instruction}\n\nEarlier team results:\n{_board(blackboard)}",
        },
    ]
    with (
        trace.in_step(worker.step or worker.name),
        trace.span("step", f"worker:{worker.name}", role=worker.name) as span,
    ):
        if worker.executor is not None:
            loop = await run_tool_loop(worker.llm, messages, worker.executor, max_turns=worker.max_turns)
            messages = [*loop.messages, {"role": "user", "content": "Now return your result in the required format."}]
        with trace.in_step("handoff"), trace.span("handoff", worker.name, role=worker.name) as handoff:
            try:
                output, responses = await structured(worker.llm, messages, worker.output_model, retries=1)
                handoff.output = output.model_dump()
                handoff.attrs.update({"accepted": True, "repair_attempts": len(responses) - 1})
            except StructuredOutputError as exc:
                handoff.attrs["accepted"] = False
                handoff.error = str(exc)[:500]
                output = None
        span.output = handoff.output
    return output


def _board(blackboard: dict[str, Any]) -> str:
    return json.dumps(blackboard, indent=2, ensure_ascii=False) if blackboard else "(none yet)"

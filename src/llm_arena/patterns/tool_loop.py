"""The function-calling loop: model → tool calls → results → model, until an answer or max_turns."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Literal

from llm_arena.core.trace import Trace
from llm_arena.llm.client import LLMClient
from llm_arena.llm.tool_mode import tool_result_message
from llm_arena.llm.types import Message
from llm_arena.tools.executor import Executor

StopReason = Literal["final", "max_turns"]


@dataclass
class LoopResult:
    final: str
    stop_reason: StopReason
    turns: int
    messages: list[Message]


async def run_tool_loop(
    llm: LLMClient,
    messages: list[Message],
    executor: Executor,
    *,
    max_turns: int = 8,
    trace: Trace | None = None,
    step: str | None = None,
    tool_step: str | None = None,
) -> LoopResult:
    """`step` / `tool_step`: workflow steps for the model calls and the tool executions (default: inherit)."""
    history = list(messages)
    schemas = executor.registry.schemas() or None
    for turn in range(1, max_turns + 1):
        with _in(trace, step):
            response = await llm.complete(history, tools=schemas)
        history.append(response.raw_message)
        if not response.tool_calls:
            return LoopResult(response.content, "final", turn, history)
        for call in response.tool_calls:
            with _in(trace, tool_step):
                outcome = await executor.execute(call)
            history.append(tool_result_message(llm.spec.tool_mode, call, outcome.content))

    # Out of turns: ask once more without tools, so a looping agent still yields an answer we
    # can score — the stop reason keeps the failure visible.
    history.append({"role": "user", "content": "You have used all tool calls. Give your final answer now."})
    with _in(trace, step):
        response = await llm.complete(history)
    history.append(response.raw_message)
    return LoopResult(response.content, "max_turns", max_turns, history)


def _in(trace: Trace | None, step: str | None) -> contextlib.AbstractContextManager[None]:
    return trace.in_step(step) if trace is not None else contextlib.nullcontext()

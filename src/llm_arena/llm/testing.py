"""Deterministic fakes for tests: no test may need a model server or an API key."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.types import LLMResponse, Message, ToolCall, Usage

Reply = str | LLMResponse | Callable[[list[Message]], "str | LLMResponse"]


def tool_call(name: str, **args: Any) -> LLMResponse:
    call = ToolCall(name=name, args=args, id=f"call_{name}", raw_args=json.dumps(args))
    raw = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": call.id, "type": "function", "function": {"name": name, "arguments": call.raw_args}}],
    }
    return LLMResponse(content="", tool_calls=[call], raw_message=raw, usage=Usage(10, 5, 0.001))


class ScriptedLLM:
    """Plays back replies in order; a callable reply can inspect the conversation.

    When the script runs out, the last reply repeats — convenient for "always answer X" fakes.
    Every received message list is recorded in `calls` for assertions.
    """

    def __init__(self, replies: Sequence[Reply], *, name: str = "scripted", spec: ModelSpec | None = None):
        if not replies:
            raise ValueError("ScriptedLLM needs at least one reply")
        self.spec = spec or ModelSpec(
            name=name, provider="openai_compatible", model=name, capabilities=Capabilities(vision=True)
        )
        self._replies = list(replies)
        self.calls: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])  # snapshot: callers keep appending
        reply = self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, str):
            return LLMResponse(
                content=reply,
                raw_message={"role": "assistant", "content": reply},
                usage=Usage(len(str(messages)) // 4, len(reply) // 4, 0.001),
                model=self.spec.model,
            )
        return reply

"""Does a model actually work? Smoke-tests chat, tool calling and structured output (`arena models ping`)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import BaseModel

from llm_arena.llm.client import LLMClient, structured
from llm_arena.llm.spec import ModelSpec

_ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}


@dataclass
class ProbeResult:
    name: str
    reachable: bool = False
    chat_ok: bool = False
    tools_ok: bool = False
    structured_ok: bool = False
    first_token_latency_s: float | None = None
    errors: list[str] = field(default_factory=list)


class _Probe(BaseModel):
    city: str
    population_millions: float


async def probe_model(spec: ModelSpec, client: LLMClient) -> ProbeResult:
    """Smoke-test chat, tool calling and structured output — a capability report per model."""
    result = ProbeResult(spec.name)
    started = time.perf_counter()
    try:
        reply = await client.complete([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=512)
        result.reachable = True
        result.first_token_latency_s = time.perf_counter() - started
        result.chat_ok = "pong" in reply.content.lower()
    except Exception as exc:
        result.errors.append(f"chat: {exc}")
        return result
    try:
        reply = await client.complete(
            [{"role": "user", "content": "Use the add tool to compute 19 + 23."}], tools=[_ADD_TOOL]
        )
        result.tools_ok = any(call.name == "add" and call.args == {"a": 19, "b": 23} for call in reply.tool_calls)
    except Exception as exc:
        result.errors.append(f"tools: {exc}")
    try:
        parsed, _ = await structured(
            client,
            [{"role": "user", "content": "Give Tokyo's city name and population in millions."}],
            _Probe,
            retries=1,
        )
        result.structured_ok = parsed.city.lower().startswith("tokyo")
    except Exception as exc:
        result.errors.append(f"structured: {exc}")
    return result

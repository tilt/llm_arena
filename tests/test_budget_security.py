"""Concurrency and refusal guarantees for spend reservations."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from llm_arena.llm.spec import Capabilities, ModelSpec
from llm_arena.llm.testing import ScriptedLLM
from llm_arena.llm.types import LLMResponse, Message, Usage
from llm_arena.runner.budget import BudgetGuard, StrictBudgetError


async def test_reservations_are_atomic_under_concurrency() -> None:
    guard = BudgetGuard(1.0)
    admitted = await asyncio.gather(*(guard.reserve(0.1) for _ in range(16)))
    assert sum(admitted) == 10
    assert guard.reserved_usd == pytest.approx(1.0)


class CaptureClient(ScriptedLLM):
    def __init__(self, spec: ModelSpec, cost: float = 0.01) -> None:
        super().__init__(["ok"], spec=spec)
        self.cost = cost
        self.kwargs: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.kwargs.append(
            {
                "tools": tools,
                "response_format": response_format,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        await super().complete(
            messages,
            tools=tools,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMResponse(content="ok", usage=Usage(10, 10, cost_usd=self.cost))


async def test_best_effort_does_not_change_provider_arguments() -> None:
    spec = ModelSpec(name="priced", provider="openai", model="gpt-5-mini")
    inner = CaptureClient(spec)
    client = BudgetGuard(1.0).wrap(inner)
    messages: list[Message] = [{"role": "user", "content": "hello"}]
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    await client.complete(messages, tools=tools, temperature=0.3)
    assert inner.kwargs == [
        {
            "tools": tools,
            "response_format": None,
            "temperature": 0.3,
            "max_tokens": None,
        }
    ]


async def test_best_effort_admits_unknown_price_and_image_with_a_reservation() -> None:
    spec = ModelSpec(
        name="future",
        provider="openai",
        model="gpt-future",
        capabilities=Capabilities(vision=True),
    )
    inner = CaptureClient(spec)
    guard = BudgetGuard(1.0, "best_effort")
    client = guard.wrap(inner)
    await client.complete([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:"}}]}])
    assert len(inner.calls) == 1
    assert guard.spent_usd == pytest.approx(0.01)
    assert guard.reserved_usd == 0


async def test_strict_refuses_unknown_prices_and_images_before_transport() -> None:
    unknown = ModelSpec(name="future", provider="openai", model="gpt-future", max_tokens=100)
    inner = CaptureClient(unknown)
    guard = BudgetGuard(1.0, "strict")
    with pytest.raises(StrictBudgetError, match="unknown pricing"):
        await guard.wrap(inner).complete([{"role": "user", "content": "hello"}])
    assert inner.calls == []

    vision = ModelSpec(name="vision", provider="openai", model="gpt-5-mini", max_tokens=100)
    inner = CaptureClient(vision)
    with pytest.raises(StrictBudgetError, match="image payload"):
        await guard.wrap(inner).complete(
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:"}}]}]
        )
    assert inner.calls == []


async def test_strict_free_local_model_needs_no_output_cost_bound() -> None:
    spec = ModelSpec(name="local", provider="ollama", model="local")
    inner = CaptureClient(spec, cost=0.0)
    guard = BudgetGuard(0.0, "strict")
    guard.validate_spec(spec)
    await guard.wrap(inner).complete([{"role": "user", "content": "hello"}])
    assert len(inner.calls) == 1

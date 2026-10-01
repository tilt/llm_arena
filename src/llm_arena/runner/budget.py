"""Concurrent spend reservations for best-effort and strict run budgets."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Literal

from llm_arena.llm.client import LLMClient
from llm_arena.llm.errors import LLMError
from llm_arena.llm.pricing import explicit_or_known_price, max_known_price
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.types import LLMResponse, Message

BudgetMode = Literal["best_effort", "strict"]
DEFAULT_OUTPUT_TOKENS = 4_000
TOKENS_PER_IMAGE = 1_024


class BudgetExceededError(LLMError):
    """Raised instead of making a call whose reservation does not fit."""


class StrictBudgetError(LLMError):
    """Raised before transport use when a strict upper bound cannot be established."""


class BudgetGuard:
    def __init__(self, limit_usd: float | None, mode: BudgetMode = "best_effort") -> None:
        self.limit_usd = limit_usd
        self.mode = mode
        self.spent_usd = 0.0
        self.reserved_usd = 0.0
        self._lock = asyncio.Lock()

    @property
    def exceeded(self) -> bool:
        return self.limit_usd is not None and self.spent_usd >= self.limit_usd

    @property
    def available(self) -> float | None:
        return None if self.limit_usd is None else max(0.0, self.limit_usd - self.spent_usd - self.reserved_usd)

    async def reserve(self, amount_usd: float) -> bool:
        async with self._lock:
            if self.limit_usd is not None and self.spent_usd + self.reserved_usd + amount_usd > self.limit_usd:
                return False
            self.reserved_usd += amount_usd
            return True

    async def settle(self, reserved_usd: float, actual_usd: float) -> None:
        async with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - reserved_usd)
            self.spent_usd += actual_usd

    def charge(self, amount_usd: float) -> None:
        """Compatibility helper for synchronous test bookkeeping; concurrent paths use settle()."""
        self.spent_usd += amount_usd

    def validate_spec(self, spec: ModelSpec) -> None:
        if self.limit_usd is None or self.mode != "strict":
            return
        prices = explicit_or_known_price(spec)
        if prices is None:
            raise StrictBudgetError(
                f"strict budget: {spec.name} has unknown input or output pricing; use best_effort or configure both prices"
            )
        if prices == (0.0, 0.0):
            return
        if spec.max_tokens is None:
            raise StrictBudgetError(
                f"strict budget: {spec.name} has no finite max_tokens; use best_effort or set max_tokens on the model"
            )

    def wrap(self, client: LLMClient) -> LLMClient:
        return BudgetedClient(client, self)


class BudgetedClient:
    def __init__(self, client: LLMClient, guard: BudgetGuard) -> None:
        self._client = client
        self._guard = guard

    @property
    def spec(self) -> ModelSpec:
        return self._client.spec

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        reservation = self._estimate(messages, tools, response_format, max_tokens)
        if not await self._guard.reserve(reservation):
            raise BudgetExceededError(f"spend limit of ${self._guard.limit_usd:.2f} reached")
        try:
            response = await self._client.complete(
                messages,
                tools=tools,
                response_format=response_format,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except BaseException:
            await self._guard.settle(reservation, 0.0)
            raise
        await self._guard.settle(reservation, response.usage.cost_usd)
        if self._guard.mode == "strict" and response.usage.cost_usd > reservation:
            raise StrictBudgetError(
                f"strict budget invariant failed for {self.spec.name}: actual cost exceeded its reservation"
            )
        return response

    def _estimate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> float:
        if self._guard.limit_usd is None:
            return 0.0
        known = explicit_or_known_price(self.spec)
        if known is None:
            if self._guard.mode == "strict":
                raise StrictBudgetError(
                    f"strict budget: {self.spec.name} has unknown pricing; use best_effort or configure both prices"
                )
            known = max_known_price(self.spec.provider)
        if known == (0.0, 0.0):
            return 0.0
        images = _image_count(messages)
        if images and self._guard.mode == "strict":
            raise StrictBudgetError(
                f"strict budget: {self.spec.name} has an image payload without a supported cost bound; use best_effort"
            )
        output_tokens = max_tokens if max_tokens is not None else self.spec.max_tokens
        if output_tokens is None:
            if self._guard.mode == "strict":
                raise StrictBudgetError(
                    f"strict budget: {self.spec.name} has no finite max_tokens; use best_effort or configure max_tokens"
                )
            output_tokens = DEFAULT_OUTPUT_TOKENS
        payload = {"messages": messages, "tools": tools, "response_format": response_format}
        input_tokens = math.ceil(len(json.dumps(payload, default=str, sort_keys=True).encode("utf-8")) / 4)
        input_tokens += images * TOKENS_PER_IMAGE
        return (input_tokens * known[0] + output_tokens * known[1]) / 1_000_000


def _image_count(value: Any) -> int:
    if isinstance(value, dict):
        own = int(value.get("type") in ("image", "image_url", "input_image"))
        return own + sum(_image_count(item) for item in value.values())
    if isinstance(value, list):
        return sum(_image_count(item) for item in value)
    return 0

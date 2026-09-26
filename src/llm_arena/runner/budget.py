"""Spend limit for a run: every model call (pipeline and judge) is charged; once the limit is reached,
further calls fail and no new trials start. Essential for bring-your-own-key browser runs.
"""

from __future__ import annotations

from typing import Any

from llm_arena.llm.client import LLMClient
from llm_arena.llm.errors import LLMError
from llm_arena.llm.spec import ModelSpec
from llm_arena.llm.types import LLMResponse, Message


class BudgetExceededError(LLMError):
    """Raised instead of making a call once the run's spend limit is reached."""


class BudgetGuard:
    def __init__(self, limit_usd: float | None) -> None:
        self.limit_usd = limit_usd
        self.spent_usd = 0.0

    @property
    def exceeded(self) -> bool:
        return self.limit_usd is not None and self.spent_usd >= self.limit_usd

    def charge(self, amount_usd: float) -> None:
        self.spent_usd += amount_usd

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
        if self._guard.exceeded:
            raise BudgetExceededError(f"spend limit of ${self._guard.limit_usd:.2f} reached")
        response = await self._client.complete(
            messages, tools=tools, response_format=response_format, temperature=temperature, max_tokens=max_tokens
        )
        self._guard.charge(response.usage.cost_usd)
        return response
